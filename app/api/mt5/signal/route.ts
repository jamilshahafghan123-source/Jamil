/** GET /api/mt5/signal?symbol=&timeframe= -> bridge GET /signal */
import type { NextRequest } from "next/server";

import { getSignal } from "@/lib/bridge";
import { fail, handle, ok } from "@/lib/api-response";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return handle(async () => {
    const symbol = request.nextUrl.searchParams.get("symbol")?.trim();
    const timeframe = request.nextUrl.searchParams.get("timeframe")?.trim() || undefined;
    if (!symbol) {
      return fail("invalid_request", "A 'symbol' query parameter is required.", 400);
    }
    // Read-only: the pipeline proposes an order, it never places one.
    return ok(await getSignal({ symbol, timeframe }));
  });
}
