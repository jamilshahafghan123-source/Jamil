/** GET /api/mt5/symbols?search= -> bridge GET /symbols */
import type { NextRequest } from "next/server";

import { getSymbols } from "@/lib/bridge";
import { handle, ok } from "@/lib/api-response";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return handle(async () => {
    const search = request.nextUrl.searchParams.get("search")?.trim() || undefined;
    return ok(await getSymbols(search));
  });
}
