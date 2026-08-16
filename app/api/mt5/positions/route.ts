/** GET /api/mt5/positions -> bridge GET /positions */
import { getPositions } from "@/lib/bridge";
import { handle, ok } from "@/lib/api-response";

export const dynamic = "force-dynamic";

export async function GET() {
  return handle(async () => ok(await getPositions()));
}
