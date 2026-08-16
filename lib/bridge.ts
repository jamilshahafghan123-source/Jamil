/**
 * Server-side client for the FastAPI MT5 bridge.
 *
 * `server-only` makes importing this from a client component a build error, so
 * MT5_BRIDGE_TOKEN can never be bundled into browser JavaScript. Every browser
 * request reaches the bridge through the route handlers in app/api/mt5/*.
 */
import "server-only";

import { readFileSync } from "node:fs";
import { Agent, type Dispatcher } from "undici";

import type {
  Account,
  Candle,
  OrderRequestBody,
  Position,
  SymbolSummary,
  Tick,
  TradeResult,
} from "./types";

export type BridgeErrorCode =
  /** The bridge could not be reached at all: DNS, refused, timeout, TLS. */
  | "bridge_offline"
  /** The bridge answered, but with an error status. */
  | "bridge_error"
  /** The server is missing MT5_BRIDGE_URL / MT5_BRIDGE_TOKEN. */
  | "not_configured"
  /** Live execution is switched off by MT5_ALLOW_LIVE_ORDERS. */
  | "live_execution_disabled";

export class BridgeError extends Error {
  readonly code: BridgeErrorCode;
  readonly status: number;
  readonly details: unknown;

  constructor(
    code: BridgeErrorCode,
    message: string,
    status: number,
    details?: unknown,
  ) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
    this.status = status;
    this.details = details ?? null;
  }

  get offline(): boolean {
    return this.code === "bridge_offline" || this.code === "not_configured";
  }
}

type BridgeConfig = {
  baseUrl: string;
  token: string;
  apiPrefix: string;
  timeoutMs: number;
};

function readConfig(): BridgeConfig {
  const baseUrl = process.env.MT5_BRIDGE_URL?.trim();
  const token = process.env.MT5_BRIDGE_TOKEN?.trim();

  if (!baseUrl || !token) {
    const missing = [
      !baseUrl && "MT5_BRIDGE_URL",
      !token && "MT5_BRIDGE_TOKEN",
    ].filter(Boolean);
    throw new BridgeError(
      "not_configured",
      `MT5 bridge is not configured on the server (missing ${missing.join(" and ")}).`,
      503,
    );
  }

  // The bridge serves market/trading routes under a version prefix and /health
  // at the root. Point MT5_BRIDGE_API_PREFIX at "" for a bridge that serves the
  // trading routes at the root instead.
  const apiPrefix = (process.env.MT5_BRIDGE_API_PREFIX ?? "/api/v1").replace(/\/$/, "");

  return {
    baseUrl: baseUrl.replace(/\/$/, ""),
    token,
    apiPrefix,
    timeoutMs: Number(process.env.MT5_BRIDGE_TIMEOUT_MS ?? 10_000),
  };
}

/** True only when the operator has explicitly turned on live execution. */
export function liveOrdersEnabled(): boolean {
  return process.env.MT5_ALLOW_LIVE_ORDERS?.trim().toLowerCase() === "true";
}

export function bridgeConfigured(): boolean {
  return Boolean(process.env.MT5_BRIDGE_URL?.trim() && process.env.MT5_BRIDGE_TOKEN?.trim());
}

/**
 * A dispatcher is only needed for a bridge behind a self-signed certificate.
 * Scoping it here keeps the rest of the process on normal TLS verification.
 */
let dispatcher: Dispatcher | null | undefined;

function tlsDispatcher(): Dispatcher | undefined {
  if (dispatcher !== undefined) return dispatcher ?? undefined;

  const caPath = process.env.MT5_BRIDGE_CA_CERT?.trim();
  const insecure = process.env.MT5_BRIDGE_INSECURE_TLS?.trim().toLowerCase() === "true";

  if (caPath) {
    dispatcher = new Agent({ connect: { ca: readFileSync(caPath, "utf8") } });
  } else if (insecure) {
    // Development escape hatch for a self-signed bridge certificate.
    console.warn(
      "[mt5-bridge] MT5_BRIDGE_INSECURE_TLS=true - bridge certificate is NOT verified. " +
        "Use MT5_BRIDGE_CA_CERT outside local development.",
    );
    dispatcher = new Agent({ connect: { rejectUnauthorized: false } });
  } else {
    dispatcher = null;
  }
  return dispatcher ?? undefined;
}

function describeTransportFailure(error: unknown): string {
  const cause = (error as { cause?: { code?: string } })?.cause;
  const code = cause?.code ?? (error as { code?: string })?.code;
  switch (code) {
    case "ECONNREFUSED":
      return "the bridge refused the connection";
    case "ENOTFOUND":
    case "EAI_AGAIN":
      return "the bridge host could not be resolved";
    case "DEPTH_ZERO_SELF_SIGNED_CERT":
    case "SELF_SIGNED_CERT_IN_CHAIN":
    case "UNABLE_TO_VERIFY_LEAF_SIGNATURE":
      return "the bridge TLS certificate could not be verified (set MT5_BRIDGE_CA_CERT)";
    case "CERT_HAS_EXPIRED":
      return "the bridge TLS certificate has expired";
    default:
      return code ? `connection failed (${code})` : "connection failed";
  }
}

async function request<T>(
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const config = readConfig();
  const url = `${config.baseUrl}${path}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: init.method ?? "GET",
      headers: {
        // The bridge accepts either; sending both keeps this client working
        // against an X-API-Key-only deployment too.
        Authorization: `Bearer ${config.token}`,
        "X-API-Key": config.token,
        ...(init.body ? { "Content-Type": "application/json" } : {}),
      },
      body: init.body ? JSON.stringify(init.body) : undefined,
      signal: AbortSignal.timeout(config.timeoutMs),
      cache: "no-store",
      // @ts-expect-error - undici dispatcher is accepted by Node's fetch
      dispatcher: tlsDispatcher(),
    });
  } catch (error) {
    const reason =
      error instanceof Error && error.name === "TimeoutError"
        ? `no response within ${config.timeoutMs}ms`
        : describeTransportFailure(error);
    // Deliberately reports the URL but never the token.
    throw new BridgeError("bridge_offline", `MT5 Bridge Offline: ${reason}.`, 503, {
      url,
    });
  }

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const message =
      pickString(payload, "message") ??
      pickString(payload, "detail") ??
      `Bridge responded with HTTP ${response.status}.`;
    throw new BridgeError("bridge_error", message, response.status, payload);
  }

  return payload as T;
}

function pickString(payload: unknown, key: string): string | null {
  if (!payload || typeof payload !== "object") return null;
  const value = (payload as Record<string, unknown>)[key];
  return typeof value === "string" ? value : null;
}

function apiPath(path: string): string {
  return `${readConfig().apiPrefix}${path}`;
}

// --- endpoints ---------------------------------------------------------------

export type BridgeHealth = {
  status: string;
  service?: string;
  version?: string;
};

export type BridgeReadiness = {
  connected: boolean;
  login: number | null;
  trade_mode: string | null;
  is_demo: boolean;
  live_trading_allowed: boolean;
  detail: string | null;
};

/** GET /health - liveness, no MT5 account required. */
export function getHealth(): Promise<BridgeHealth> {
  return request<BridgeHealth>("/health");
}

/** GET /health/ready - is the terminal actually connected and on which account. */
export function getReadiness(): Promise<BridgeReadiness> {
  return request<BridgeReadiness>("/health/ready");
}

/** GET /account */
export function getAccount(): Promise<Account> {
  return request<Account>(apiPath("/account"));
}

/** GET /symbols */
export function getSymbols(search?: string): Promise<SymbolSummary[]> {
  const query = search ? `?search=${encodeURIComponent(search)}&limit=500` : "?limit=500";
  return request<SymbolSummary[]>(apiPath(`/symbols${query}`));
}

/** GET /tick/{symbol} */
export function getTick(symbol: string): Promise<Tick> {
  return request<Tick>(apiPath(`/tick/${encodeURIComponent(symbol)}`));
}

/** GET /candles */
export function getCandles(params: {
  symbol: string;
  timeframe: string;
  count: number;
}): Promise<{ symbol: string; timeframe: string; count: number; candles: Candle[] }> {
  const query = new URLSearchParams({
    symbol: params.symbol,
    timeframe: params.timeframe,
    count: String(params.count),
  });
  return request(apiPath(`/candles?${query.toString()}`));
}

/** GET /positions */
export function getPositions(): Promise<Position[]> {
  return request<Position[]>(apiPath("/positions"));
}

/** POST /orders */
export function postOrder(body: OrderRequestBody): Promise<TradeResult> {
  return request<TradeResult>(apiPath("/orders"), { method: "POST", body });
}

/** POST /positions/{ticket}/close */
export function closePosition(
  ticket: number,
  body: { volume?: number } = {},
): Promise<TradeResult> {
  return request<TradeResult>(apiPath(`/positions/${ticket}/close`), {
    method: "POST",
    body,
  });
}
