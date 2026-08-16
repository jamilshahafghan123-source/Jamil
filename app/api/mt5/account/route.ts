/** GET /api/mt5/account -> bridge GET /account */
import { getAccount } from "@/lib/bridge";
import { handle, ok } from "@/lib/api-response";

export const dynamic = "force-dynamic";

export async function GET() {
  return handle(async () => ok(await getAccount()));
}
