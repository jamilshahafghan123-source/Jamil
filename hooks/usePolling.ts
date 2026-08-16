"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiClientError, apiFetch } from "@/lib/client";

export type PollState<T> = {
  data: T | null;
  error: ApiClientError | null;
  /** True only until the first response arrives. */
  loading: boolean;
  /** True while a background refresh is in flight. */
  refreshing: boolean;
  lastUpdated: number | null;
  refresh: () => void;
};

/**
 * Polls one of the /api/mt5/* routes.
 *
 * Keeps the last good data on screen when a refresh fails (so a blip does not
 * blank the desk), pauses while the tab is hidden, and aborts in-flight
 * requests on unmount.
 */
export function usePolling<T>(
  url: string | null,
  intervalMs: number,
  options: { enabled?: boolean } = {},
): PollState<T> {
  const enabled = (options.enabled ?? true) && Boolean(url);

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  const controllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      controllerRef.current?.abort();
    };
  }, []);

  const load = useCallback(async () => {
    if (!url) return;

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setRefreshing(true);

    try {
      const result = await apiFetch<T>(url, { signal: controller.signal });
      if (!mountedRef.current || controller.signal.aborted) return;
      setData(result);
      setError(null);
      setLastUpdated(Date.now());
    } catch (caught) {
      if (!mountedRef.current || controller.signal.aborted) return;
      if ((caught as Error).name === "AbortError") return;
      setError(
        caught instanceof ApiClientError
          ? caught
          : new ApiClientError("unknown", (caught as Error).message),
      );
    } finally {
      if (mountedRef.current && !controller.signal.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [url]);

  // Reset when the target changes (e.g. a different symbol).
  useEffect(() => {
    if (!enabled) return;
    setLoading(true);
    void load();
  }, [enabled, load]);

  useEffect(() => {
    if (!enabled || intervalMs <= 0) return;

    const tick = () => {
      if (document.visibilityState === "visible") void load();
    };
    const timer = window.setInterval(tick, intervalMs);

    // Catch up immediately when the tab comes back to the foreground.
    const onVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, intervalMs, load]);

  return { data, error, loading, refreshing, lastUpdated, refresh: load };
}
