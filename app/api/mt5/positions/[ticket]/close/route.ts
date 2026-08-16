/**
 * POST /api/mt5/positions/{ticket}/close -> bridge POST /positions/{ticket}/close
 *
 * Closing is execution too, so it sits behind the same MT5_ALLOW_LIVE_ORDERS
 * flag. There is no dry-run for a close, so the route refuses outright rather
 * than reporting a close that never happened.
 */
import { closePosition, liveOrdersEnabled } from "@/lib/bridge";
import { fail, handle, ok } from "@/lib/api-response";
import type { OrderOutcome } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ ticket: string }> },
) {
  return handle(async () => {
    const { ticket: rawTicket } = await params;
    const ticket = Number(rawTicket);
    if (!Number.isInteger(ticket) || ticket <= 0) {
      return fail("invalid_request", "Position ticket must be a positive integer.", 400);
    }

    const body = (await request.json().catch(() => ({}))) as { volume?: unknown };
    const payload: { volume?: number } = {};
    if (body?.volume != null && body.volume !== "") {
      const volume = Number(body.volume);
      if (!Number.isFinite(volume) || volume <= 0) {
        return fail("invalid_request", "'volume' must be a positive number.", 400);
      }
      payload.volume = volume;
    }

    if (!liveOrdersEnabled()) {
      return fail(
        "live_execution_disabled",
        "Live execution is disabled on the server (MT5_ALLOW_LIVE_ORDERS is not true), " +
          `so position ${ticket} was not closed.`,
        423,
      );
    }

    const result = await closePosition(ticket, payload);
    return ok<OrderOutcome>({ ...result, executed: true });
  });
}
