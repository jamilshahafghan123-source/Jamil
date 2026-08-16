/** GET /api/mt5/risk -> bridge GET /risk */
import { getRisk } from "@/lib/bridge";
import { handle, ok } from "@/lib/api-response";

export const dynamic = "force-dynamic";

export async function GET() {
  return handle(async () => ok(await getRisk()));
}
