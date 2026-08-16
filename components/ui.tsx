"use client";

import type { ReactNode } from "react";

import type { ApiClientError } from "@/lib/client";

export function Panel({
  title,
  actions,
  children,
  tight,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
  tight?: boolean;
}) {
  return (
    <section className="panel">
      <header className="panel-head">
        <h2 className="panel-title">{title}</h2>
        {actions ? <div className="spacer" /> : null}
        {actions}
      </header>
      <div className={tight ? "panel-body tight" : "panel-body"}>{children}</div>
    </section>
  );
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

export function RefreshIndicator({
  refreshing,
  label,
}: {
  refreshing: boolean;
  label: string;
}) {
  return (
    <span className="muted" style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 6 }}>
      {refreshing ? <Spinner /> : null}
      {label}
    </span>
  );
}

/**
 * One consistent error presentation. An unreachable bridge is always phrased as
 * "MT5 Bridge Offline" so it can never be mistaken for a working desk.
 */
export function ErrorNotice({
  error,
  onRetry,
}: {
  error: ApiClientError;
  onRetry?: () => void;
}) {
  return (
    <div className="notice error" role="alert">
      <div style={{ flex: 1 }}>
        <strong>{error.offline ? "MT5 Bridge Offline" : humanizeCode(error.code)}</strong>
        <span>{error.message}</span>
      </div>
      {onRetry ? (
        <button type="button" className="btn small ghost" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function Skeleton({ width = "100%", height = 14 }: { width?: string; height?: number }) {
  return <div className="skeleton" style={{ width, height }} />;
}

export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div style={{ display: "grid", gap: 9 }}>
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} width={index % 2 ? "72%" : "100%"} />
      ))}
    </div>
  );
}

export function humanizeCode(code: string): string {
  switch (code) {
    case "not_configured":
      return "Bridge not configured";
    case "bridge_offline":
      return "MT5 Bridge Offline";
    case "live_execution_disabled":
      return "Live execution disabled";
    case "terminal_unavailable":
      return "MT5 terminal unavailable";
    case "trade_rejected":
      return "Trade rejected by MT5";
    case "risk_rejected":
      return "Blocked by the risk policy";
    case "trading_not_allowed":
      return "Trading not allowed";
    case "symbol_not_found":
      return "Symbol not found";
    default:
      return code.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  }
}
