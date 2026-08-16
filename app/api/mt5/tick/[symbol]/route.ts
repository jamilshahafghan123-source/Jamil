/** GET /api/mt5/tick/{symbol} -> bridge GET /tick/{symbol} */
import { getTick } from "@/lib/bridge";
import { fail, handle, ok } from "@/lib/api-response";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ symbol: string }> },
) {
  return handle(async () => {
    const { symbol } = await params;
    if (!/^[A-Za-z0-9._#-]{1,32}$/.test(symbol)) {
      return fail("invalid_symbol", "Symbol contains unsupported characters.", 400);
    }
    return ok(await getTick(symbol));
  });
}
