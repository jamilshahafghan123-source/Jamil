import type {
  Analysis,
  BarsResponse,
  DashboardSnapshot,
  Deal,
  ExecutionResult,
  OrderLog,
  RiskSettings,
  Signal,
  Timeframe,
  TradingMode,
} from "./types";

// Same-origin by default: nginx proxies /api and /ws to the backend, so no
// secrets or hostnames are baked into the bundle.
const BASE = import.meta.env.VITE_API_BASE ?? "";

const TOKEN_KEY = "mt5ai.token";

export const auth = {
  get token(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  },
  set(token: string) {
    localStorage.setItem(TOKEN_KEY, token);
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY);
  },
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const token = auth.token;
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${BASE}${path}`, { ...init, headers });

  if (res.status === 401) {
    auth.clear();
    window.dispatchEvent(new Event("auth:expired"));
    throw new ApiError(401, "Session expired — please sign in again");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
      if (Array.isArray(detail)) {
        detail = detail.map((d: { msg?: string }) => d.msg ?? "invalid").join("; ");
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, String(detail));
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; expires_in: number }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  dashboard: () => request<DashboardSnapshot>("/api/dashboard"),
  deals: (days = 7) => request<Deal[]>(`/api/history/deals?days=${days}`),
  orderLogs: (limit = 50) => request<OrderLog[]>(`/api/history/orders?limit=${limit}`),

  runAnalysis: () =>
    request<{ signal: Signal; analysis: Analysis }>("/api/analysis/run", {
      method: "POST",
    }),
  signals: (limit = 25) => request<Signal[]>(`/api/analysis/signals?limit=${limit}`),

  /**
   * OHLC candles for the chart, straight from MT5 via the bridge.
   *
   * Auth is the shared Bearer flow in `request()` — no token or credential
   * is ever referenced here.
   *
   * NOTE ON `symbol`: the current backend derives the symbol from its own
   * SYMBOL setting and ignores this query parameter. It is sent because the
   * documented URL includes it and it is forward-compatible; always trust
   * `response.symbol` for what was actually returned, never this argument.
   *
   * `signal` lets the caller abort an in-flight poll on unmount or when the
   * timeframe changes, so slow responses cannot land out of order.
   */
  bars: (timeframe: Timeframe = "M5", count = 100, symbol = "XAUUSD", signal?: AbortSignal) =>
    request<BarsResponse>(
      `/api/analysis/bars?symbol=${encodeURIComponent(symbol)}` +
        `&timeframe=${encodeURIComponent(timeframe)}&count=${count}`,
      { signal },
    ),
  signalDetail: (id: number) =>
    request<{ signal: Signal; analysis: Analysis; market_snapshot: unknown }>(
      `/api/analysis/signals/${id}`,
    ),

  getRisk: () => request<RiskSettings>("/api/risk/settings"),
  saveRisk: (body: Partial<RiskSettings>) =>
    request<RiskSettings>("/api/risk/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  setMode: (mode: TradingMode, confirmation?: string) =>
    request<RiskSettings>("/api/risk/mode", {
      method: "POST",
      body: JSON.stringify({ mode, confirmation }),
    }),
  toggleBot: (enabled: boolean) =>
    request<RiskSettings>("/api/risk/bot", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  emergencyStop: (closePositions = true) =>
    request<RiskSettings>(
      `/api/risk/emergency-stop?close_positions=${closePositions}`,
      { method: "POST" },
    ),
  clearEmergencyStop: () =>
    request<RiskSettings>("/api/risk/emergency-stop/clear", { method: "POST" }),

  execute: (signalId: number, volume?: number) =>
    request<ExecutionResult>("/api/trading/execute", {
      method: "POST",
      body: JSON.stringify({ signal_id: signalId, volume }),
    }),
  closePosition: (ticket: number) =>
    request<{ success: boolean }>("/api/trading/close", {
      method: "POST",
      body: JSON.stringify({ ticket }),
    }),
  closeAll: () => request<{ results: unknown[] }>("/api/trading/close-all", {
    method: "POST",
  }),
};

export function liveSocketUrl(): string | null {
  const token = auth.token;
  if (!token) return null;
  const base = BASE || window.location.origin;
  const url = new URL(base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/live";
  url.search = `?token=${encodeURIComponent(token)}`;
  return url.toString();
}

// --- formatting helpers used across the dashboard -----------------------

export const fmt = {
  price: (n: number | null | undefined, digits = 2) =>
    n == null ? "—" : n.toFixed(digits),
  money: (n: number | null | undefined, currency = "") =>
    n == null
      ? "—"
      : `${n < 0 ? "-" : ""}${currency}${Math.abs(n).toLocaleString(undefined, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}`,
  signed: (n: number | null | undefined) =>
    n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(2)}`,
  time: (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleTimeString([], { hour12: false }) : "—",
  datetime: (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleString([], { hour12: false }) : "—",
};
