"use client";

import type { BridgeStatus } from "@/lib/types";

/**
 * The single source of truth on screen for whether trading is actually live.
 * Four distinct states - never a green light unless the terminal is connected.
 */
export default function ConnectionBadge({
  status,
  loading,
}: {
  status: BridgeStatus | null;
  loading: boolean;
}) {
  if (loading && !status) {
    return (
      <span className="badge muted" title="Checking the MT5 bridge">
        <span className="dot" />
        Checking bridge…
      </span>
    );
  }

  if (!status || !status.configured) {
    return (
      <span className="badge offline" title="MT5_BRIDGE_URL / MT5_BRIDGE_TOKEN are not set">
        <span className="dot" />
        Bridge not configured
      </span>
    );
  }

  if (!status.reachable) {
    return (
      <span className="badge offline" title={status.detail ?? "The bridge did not respond"}>
        <span className="dot" />
        MT5 Bridge Offline
      </span>
    );
  }

  if (!status.connected) {
    return (
      <span className="badge warn" title={status.detail ?? "The terminal is not logged in"}>
        <span className="dot" />
        Bridge up · terminal disconnected
      </span>
    );
  }

  return (
    <span
      className="badge online"
      title={`Connected to MT5 account ${status.login} (${status.trade_mode ?? "unknown"})`}
    >
      <span className="dot" />
      Bridge connected · {status.trade_mode ?? "unknown"} #{status.login}
    </span>
  );
}

export function ExecutionBadge({ status }: { status: BridgeStatus | null }) {
  const enabled = status?.live_orders_enabled ?? false;
  return (
    <span
      className={enabled ? "badge warn" : "badge muted"}
      title={
        enabled
          ? "MT5_ALLOW_LIVE_ORDERS=true - orders reach the market"
          : "MT5_ALLOW_LIVE_ORDERS is not true - orders are validated against MT5 but never sent"
      }
    >
      <span className="dot" />
      {enabled ? "Live execution ON" : "Execution disabled"}
    </span>
  );
}
