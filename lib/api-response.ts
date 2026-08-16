/** Shared helpers for the route handlers under app/api/mt5/*. */
import "server-only";

import { NextResponse } from "next/server";

import { BridgeError } from "./bridge";
import type { ApiFailure, ApiSuccess } from "./types";

export function ok<T>(data: T, status = 200): NextResponse<ApiSuccess<T>> {
  return NextResponse.json({ ok: true as const, data }, { status });
}

export function fail(
  code: string,
  message: string,
  status: number,
  options: { offline?: boolean; details?: unknown } = {},
): NextResponse<ApiFailure> {
  return NextResponse.json(
    {
      ok: false as const,
      error: {
        code,
        message,
        offline: options.offline ?? false,
        ...(options.details === undefined ? {} : { details: options.details }),
      },
    },
    { status },
  );
}

/**
 * Turns anything thrown by the bridge client into the browser envelope.
 * Unknown errors are logged server-side and reported generically, so internal
 * detail (and the token) never reaches the client.
 */
export function fromError(error: unknown): NextResponse<ApiFailure> {
  if (error instanceof BridgeError) {
    return fail(error.code, error.message, error.status, {
      offline: error.offline,
      details: error.details,
    });
  }
  console.error("[mt5-bridge] unexpected route error", error);
  return fail("internal_error", "The server hit an unexpected error.", 500);
}

/** Wraps a handler so every route shares the same failure handling. */
export async function handle<T extends NextResponse<unknown>>(
  fn: () => Promise<T>,
): Promise<T | NextResponse<ApiFailure>> {
  try {
    return await fn();
  } catch (error) {
    return fromError(error);
  }
}
