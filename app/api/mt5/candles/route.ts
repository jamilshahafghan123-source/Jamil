/** GET /api/mt5/candles?symbol=&timeframe=&count= -> bridge GET /candles */
import type { NextRequest } from "next/server";

import { getCandles } from "@/lib/bridge";
import { fail, handle, ok } from "@/lib/api-response";
import { TIMEFRAMES } from "@/lib/types";

export const dynamic = "force-dynamic";

const MAX_COUNT = 1000;

export async function GET(request: NextRequest) {
  return handle(async () => {
    const params = request.nextUrl.searchParams;
    const symbol = params.get("symbol")?.trim();
    const timeframe = params.get("timeframe")?.trim().toUpperCase() ?? "M15";
    const count = Number(params.get("count") ?? 300);

    if (!symbol) {
      return fail("invalid_request", "A 'symbol' query parameter is required.", 400);
    }
    if (!(TIMEFRAMES as readonly string[]).includes(timeframe)) {
      return fail(
        "invalid_request",
        `Unsupported timeframe '${timeframe}'. Use one of: ${TIMEFRAMES.join(", ")}.`,
        400,
      );
    }
    if (!Number.isFinite(count) || count < 1 || count > MAX_COUNT) {
      return fail("invalid_request", `'count' must be between 1 and ${MAX_COUNT}.`, 400);
    }

    return ok(await getCandles({ symbol, timeframe, count }));
  });
}
