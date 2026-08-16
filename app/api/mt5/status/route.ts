/**
 * GET /api/mt5/status -> bridge GET /health (+ /health/ready)
 *
 * Drives the connection indicator. Never throws for an unreachable bridge:
 * "offline" is a normal, reportable state here.
 */
import { bridgeConfigured, getHealth, getReadiness, liveOrdersEnabled } from "@/lib/bridge";
import { ok } from "@/lib/api-response";
import type { BridgeStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET() {
  const base: BridgeStatus = {
    configured: bridgeConfigured(),
    reachable: false,
    connected: false,
    login: null,
    trade_mode: null,
    is_demo: false,
    live_orders_enabled: liveOrdersEnabled(),
    detail: null,
  };

  if (!base.configured) {
    return ok<BridgeStatus>({
      ...base,
      detail: "Server is missing MT5_BRIDGE_URL / MT5_BRIDGE_TOKEN.",
    });
  }

  try {
    await getHealth();
  } catch (error) {
    return ok<BridgeStatus>({
      ...base,
      detail: error instanceof Error ? error.message : "MT5 Bridge Offline.",
    });
  }

  // The bridge process is up; ask whether the terminal behind it is logged in.
  try {
    const readiness = await getReadiness();
    return ok<BridgeStatus>({
      ...base,
      reachable: true,
      connected: readiness.connected,
      login: readiness.login,
      trade_mode: readiness.trade_mode,
      is_demo: readiness.is_demo,
      detail: readiness.detail,
    });
  } catch (error) {
    return ok<BridgeStatus>({
      ...base,
      reachable: true,
      detail:
        error instanceof Error ? error.message : "Bridge reachable, terminal state unknown.",
    });
  }
}
