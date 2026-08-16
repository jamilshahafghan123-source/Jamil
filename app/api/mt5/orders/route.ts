/**
 * POST /api/mt5/orders -> bridge POST /orders
 *
 * Safety flag: unless MT5_ALLOW_LIVE_ORDERS=true, the order is still sent to the
 * bridge but as a `dry_run`, so the caller gets the terminal's real order_check
 * verdict (retcode, comment, margin) and the route answers 423 Locked. Nothing
 * reaches the market, and no success is invented.
 */
import { liveOrdersEnabled, postOrder } from "@/lib/bridge";
import { fail, handle, ok } from "@/lib/api-response";
import type { OrderOutcome, OrderRequestBody, OrderSide, OrderType } from "@/lib/types";

export const dynamic = "force-dynamic";

const SIDES: OrderSide[] = ["buy", "sell"];
const TYPES: OrderType[] = ["market", "limit", "stop"];

function parseBody(raw: unknown): OrderRequestBody | string {
  if (!raw || typeof raw !== "object") return "Request body must be a JSON object.";
  const body = raw as Record<string, unknown>;

  const symbol = typeof body.symbol === "string" ? body.symbol.trim() : "";
  if (!symbol) return "'symbol' is required.";

  const side = body.side as OrderSide;
  if (!SIDES.includes(side)) return "'side' must be 'buy' or 'sell'.";

  const type = (body.type ?? "market") as OrderType;
  if (!TYPES.includes(type)) return "'type' must be 'market', 'limit' or 'stop'.";

  const volume = Number(body.volume);
  if (!Number.isFinite(volume) || volume <= 0) return "'volume' must be a positive number.";

  const order: OrderRequestBody = { symbol, side, volume, type };

  if (type === "market") {
    if (body.price != null) return "'price' does not apply to market orders.";
  } else {
    const price = Number(body.price);
    if (!Number.isFinite(price) || price <= 0) {
      return `'price' is required for ${type} orders.`;
    }
    order.price = price;
  }

  for (const level of ["sl", "tp"] as const) {
    if (body[level] == null || body[level] === "") continue;
    const value = Number(body[level]);
    if (!Number.isFinite(value) || value < 0) return `'${level}' must be a positive price.`;
    order[level] = value;
  }

  if (typeof body.comment === "string" && body.comment.trim()) {
    order.comment = body.comment.trim().slice(0, 24);
  }
  if (body.dry_run === true) order.dry_run = true;

  return order;
}

export async function POST(request: Request) {
  return handle(async () => {
    const raw = await request.json().catch(() => null);
    const parsed = parseBody(raw);
    if (typeof parsed === "string") {
      return fail("invalid_request", parsed, 400);
    }

    // The caller explicitly asked to validate only.
    if (parsed.dry_run) {
      const result = await postOrder(parsed);
      return ok<OrderOutcome>({ ...result, executed: false });
    }

    if (!liveOrdersEnabled()) {
      // Real validation against the terminal, but nothing is sent to the market.
      const check = await postOrder({ ...parsed, dry_run: true });
      return fail(
        "live_execution_disabled",
        "Live order execution is disabled on the server (MT5_ALLOW_LIVE_ORDERS is not " +
          "true). The order was validated against MT5 but not sent.",
        423,
        { details: { ...check, executed: false } },
      );
    }

    const result = await postOrder(parsed);
    return ok<OrderOutcome>({ ...result, executed: true });
  });
}
