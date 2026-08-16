/**
 * GET  /api/mt5/bot  -> bridge GET  /bot/status
 * POST /api/mt5/bot  -> bridge POST /bot/start | /bot/stop
 *
 * Starting the loop is an execution action, so it sits behind the same
 * MT5_ALLOW_LIVE_ORDERS flag as placing an order. Stopping is always allowed —
 * a kill switch that can be disabled is not a kill switch.
 */
import { getBotStatus, liveOrdersEnabled, startBot, stopBot } from "@/lib/bridge";
import { fail, handle, ok } from "@/lib/api-response";

export const dynamic = "force-dynamic";

export async function GET() {
  return handle(async () => ok(await getBotStatus()));
}

export async function POST(request: Request) {
  return handle(async () => {
    const body = (await request.json().catch(() => ({}))) as {
      action?: string;
      symbol?: string;
      timeframe?: string;
    };

    if (body?.action === "stop") {
      return ok(await stopBot());
    }
    if (body?.action !== "start") {
      return fail("invalid_request", "'action' must be 'start' or 'stop'.", 400);
    }

    if (!liveOrdersEnabled()) {
      return fail(
        "live_execution_disabled",
        "Live execution is disabled on the server (MT5_ALLOW_LIVE_ORDERS is not " +
          "true), so the trading bot was not started.",
        423,
      );
    }

    return ok(
      await startBot({ symbol: body.symbol, timeframe: body.timeframe }),
    );
  });
}
