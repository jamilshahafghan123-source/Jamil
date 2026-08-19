import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { api, ApiError, fmt } from "../lib/api";
import type { Bar as BarData, Timeframe } from "../lib/types";
import { Empty, Spinner } from "./Primitives";

/**
 * Live XAUUSD candlestick chart.
 *
 * Data comes from GET /api/analysis/bars through the shared authenticated
 * `api` client, which means the MT5 bridge token never reaches the browser.
 * Nothing here is generated or simulated: if the request fails the chart says
 * so and keeps the last real candles rather than inventing any.
 *
 * Drawn as plain SVG so the dashboard gains no new dependency.
 */

const ALL_TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

/**
 * The bridge understands all seven timeframes, but the backend's
 * /api/analysis/bars validates against services/indicators.TIMEFRAMES, which
 * is currently ["M1", "M5", "M15", "H1"]. The other three answer 422.
 *
 * They are seeded here so the buttons are honestly disabled instead of
 * failing on click. A 422 at runtime adds to this set too, so if the backend
 * list is ever widened the extra timeframes light up on their own with no
 * frontend change.
 */
const INITIALLY_UNSUPPORTED: Timeframe[] = ["M30", "H4", "D1"];

const DEFAULT_TIMEFRAME: Timeframe = "M5";
const BAR_COUNT = 100;
const POLL_MS = 5_000;

const PRICE_H = 260;
const VOLUME_H = 52;
const PAD_TOP = 10;
const PAD_RIGHT = 58;
const PAD_LEFT = 8;
const AXIS_H = 18;
const CHART_H = PAD_TOP + PRICE_H + VOLUME_H + AXIS_H;

/**
 * Sorts candles oldest-first, drops anything unparseable, and collapses
 * duplicate timestamps (the newest wins, which is what an in-progress candle
 * needs when it is re-sent each poll).
 */
function normaliseBars(raw: BarData[] | undefined): BarData[] {
  const byTime = new Map<number, BarData>();
  for (const bar of raw ?? []) {
    const ms = Date.parse(bar.time);
    if (!Number.isFinite(ms)) continue;
    if (
      !Number.isFinite(bar.open) ||
      !Number.isFinite(bar.high) ||
      !Number.isFinite(bar.low) ||
      !Number.isFinite(bar.close)
    ) {
      continue;
    }
    byTime.set(ms, bar);
  }
  return [...byTime.entries()].sort((a, b) => a[0] - b[0]).map(([, bar]) => bar);
}

/** Time label density: enough to orient, never enough to collide. */
function labelStep(count: number, width: number): number {
  const maxLabels = Math.max(2, Math.floor(width / 74));
  return Math.max(1, Math.ceil(count / maxLabels));
}

function axisTime(iso: string, timeframe: Timeframe): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (timeframe === "D1") {
    return d.toLocaleDateString([], { day: "2-digit", month: "short" });
  }
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function BarChart() {
  const [timeframe, setTimeframe] = useState<Timeframe>(DEFAULT_TIMEFRAME);
  const [bars, setBars] = useState<BarData[]>([]);
  const [symbol, setSymbol] = useState("XAUUSD");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [unsupported, setUnsupported] = useState<Set<Timeframe>>(
    () => new Set(INITIALLY_UNSUPPORTED),
  );
  const [hover, setHover] = useState<number | null>(null);

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(720);

  // --- responsive width ---------------------------------------------------
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(260, el.clientWidth));
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Keeps the requested symbol out of the polling effect's dependencies so a
  // symbol echoed back by the server can never restart the timer.
  const symbolRef = useRef(symbol);
  symbolRef.current = symbol;

  // --- polling ------------------------------------------------------------
  // One timer, chained rather than repeating: the next fetch is only queued
  // once the previous one settles, so a slow response can never stack up
  // requests, and re-running this effect cannot leave an orphan behind.
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let controller: AbortController | null = null;

    setLoading(true);
    setHover(null);

    const schedule = () => {
      if (!cancelled) timer = window.setTimeout(run, POLL_MS);
    };

    const run = async () => {
      // Don't poll a tab nobody is looking at; the next tick picks it up.
      if (!document.hidden) {
        controller?.abort();
        controller = new AbortController();
        try {
          const res = await api.bars(timeframe, BAR_COUNT, symbolRef.current, controller.signal);
          if (cancelled) return;
          setBars(normaliseBars(res.bars));
          if (res.symbol) setSymbol(res.symbol);
          setUpdatedAt(Date.now());
          setError(null);
        } catch (e) {
          if (cancelled) return;
          // An abort is our own doing, never a failure worth showing.
          if (e instanceof DOMException && e.name === "AbortError") return;
          if (e instanceof ApiError && e.status === 422) {
            // The backend does not accept this timeframe. Remember that and
            // fall back, rather than hammering it every 5 seconds.
            setUnsupported((prev) => new Set(prev).add(timeframe));
            setError(`${timeframe} is not enabled on the backend — showing ${DEFAULT_TIMEFRAME}.`);
            setTimeframe(DEFAULT_TIMEFRAME);
            return;
          }
          setError(e instanceof Error ? e.message : String(e));
        } finally {
          if (!cancelled) setLoading(false);
        }
      }
      schedule();
    };

    void run();
    return () => {
      cancelled = true;
      controller?.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [timeframe]);

  // --- geometry -----------------------------------------------------------
  const plotW = Math.max(40, width - PAD_LEFT - PAD_RIGHT);

  const scale = useMemo(() => {
    if (!bars.length) return null;
    let lo = Infinity;
    let hi = -Infinity;
    let maxVol = 0;
    for (const b of bars) {
      if (b.low < lo) lo = b.low;
      if (b.high > hi) hi = b.high;
      if (b.tick_volume > maxVol) maxVol = b.tick_volume;
    }
    const span = hi - lo;
    const pad = span > 0 ? span * 0.08 : Math.max(0.5, hi * 0.0005);
    const top = hi + pad;
    const bottom = lo - pad;
    const range = top - bottom || 1;

    const step = plotW / bars.length;
    return {
      top,
      bottom,
      maxVol: maxVol || 1,
      step,
      bodyW: Math.max(1, Math.min(14, step * 0.62)),
      y: (price: number) => PAD_TOP + ((top - price) / range) * PRICE_H,
      x: (i: number) => PAD_LEFT + i * step + step / 2,
      volY: (v: number) =>
        PAD_TOP + PRICE_H + VOLUME_H - (v / (maxVol || 1)) * (VOLUME_H - 6),
    };
  }, [bars, plotW]);

  const priceTicks = useMemo(() => {
    if (!scale) return [];
    const out: number[] = [];
    for (let i = 0; i <= 4; i += 1) {
      out.push(scale.top - ((scale.top - scale.bottom) / 4) * i);
    }
    return out;
  }, [scale]);

  const onMove = useCallback(
    (e: ReactMouseEvent<SVGSVGElement>) => {
      if (!scale || !bars.length) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const localX = ((e.clientX - rect.left) / rect.width) * width - PAD_LEFT;
      const idx = Math.floor(localX / scale.step);
      setHover(idx >= 0 && idx < bars.length ? idx : null);
    },
    [scale, bars.length, width],
  );

  const active = hover != null ? bars[hover] : bars[bars.length - 1];
  const last = bars[bars.length - 1];
  const prev = bars.length > 1 ? bars[bars.length - 2] : undefined;
  const rising = last && prev ? last.close >= prev.close : true;

  return (
    <div className="chart">
      <div className="chart-bar">
        <div className="modes" role="group" aria-label="Chart timeframe">
          {ALL_TIMEFRAMES.map((tf) => {
            const off = unsupported.has(tf);
            return (
              <button
                key={tf}
                type="button"
                aria-pressed={tf === timeframe}
                disabled={off}
                title={
                  off
                    ? `${tf} is not enabled on this backend (/api/analysis/bars accepts M1, M5, M15, H1)`
                    : `Show ${tf} candles`
                }
                onClick={() => setTimeframe(tf)}
              >
                {tf}
              </button>
            );
          })}
        </div>

        <div className="chart-meta num">
          {loading && !bars.length ? (
            <Spinner />
          ) : active ? (
            <>
              <span className="dim">O</span> {fmt.price(active.open)}{" "}
              <span className="dim">H</span> {fmt.price(active.high)}{" "}
              <span className="dim">L</span> {fmt.price(active.low)}{" "}
              <span className="dim">C</span>{" "}
              <span className={active.close >= active.open ? "up" : "down"}>
                {fmt.price(active.close)}
              </span>{" "}
              <span className="dim">V</span> {active.tick_volume}{" "}
              <span className="dim">S</span> {active.spread}p
            </>
          ) : null}
        </div>
      </div>

      {error && <div className="chart-error">{error}</div>}

      <div className="chart-plot" ref={wrapRef}>
        {!bars.length ? (
          loading ? (
            <div className="empty">
              <Spinner /> Loading {timeframe} candles…
            </div>
          ) : (
            <Empty>No candles returned for {timeframe}.</Empty>
          )
        ) : (
          scale && (
            <svg
              width="100%"
              height={CHART_H}
              viewBox={`0 0 ${width} ${CHART_H}`}
              preserveAspectRatio="none"
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
              role="img"
              aria-label={`${symbol} ${timeframe} candlestick chart, ${bars.length} candles, last close ${
                last ? last.close : "unknown"
              }`}
            >
              {/* price grid + right-hand axis */}
              {priceTicks.map((p) => (
                <g key={p}>
                  <line
                    className="chart-grid"
                    x1={PAD_LEFT}
                    x2={PAD_LEFT + plotW}
                    y1={scale.y(p)}
                    y2={scale.y(p)}
                  />
                  <text
                    className="chart-axis"
                    x={PAD_LEFT + plotW + 6}
                    y={scale.y(p) + 3.5}
                  >
                    {fmt.price(p)}
                  </text>
                </g>
              ))}

              {/* separator above the volume lane */}
              <line
                className="chart-grid"
                x1={PAD_LEFT}
                x2={PAD_LEFT + plotW}
                y1={PAD_TOP + PRICE_H}
                y2={PAD_TOP + PRICE_H}
              />

              {/* volume */}
              {bars.map((b, i) => {
                const y = scale.volY(b.tick_volume);
                return (
                  <rect
                    key={`v${b.time}`}
                    className={b.close >= b.open ? "chart-vol up" : "chart-vol down"}
                    x={scale.x(i) - scale.bodyW / 2}
                    y={y}
                    width={scale.bodyW}
                    height={Math.max(1, PAD_TOP + PRICE_H + VOLUME_H - y)}
                  />
                );
              })}

              {/* candles */}
              {bars.map((b, i) => {
                const up = b.close >= b.open;
                const cls = up ? "up" : "down";
                const x = scale.x(i);
                const yOpen = scale.y(b.open);
                const yClose = scale.y(b.close);
                const top = Math.min(yOpen, yClose);
                const h = Math.max(1, Math.abs(yClose - yOpen));
                return (
                  <g key={b.time}>
                    <line
                      className={`chart-wick ${cls}`}
                      x1={x}
                      x2={x}
                      y1={scale.y(b.high)}
                      y2={scale.y(b.low)}
                    />
                    <rect
                      className={`chart-body ${cls}`}
                      x={x - scale.bodyW / 2}
                      y={top}
                      width={scale.bodyW}
                      height={h}
                    />
                  </g>
                );
              })}

              {/* last price marker */}
              {last && (
                <g>
                  <line
                    className={`chart-last ${rising ? "up" : "down"}`}
                    x1={PAD_LEFT}
                    x2={PAD_LEFT + plotW}
                    y1={scale.y(last.close)}
                    y2={scale.y(last.close)}
                  />
                  <rect
                    className={`chart-last-tag ${rising ? "up" : "down"}`}
                    x={PAD_LEFT + plotW + 2}
                    y={scale.y(last.close) - 8}
                    width={PAD_RIGHT - 6}
                    height={16}
                    rx={2}
                  />
                  <text
                    className="chart-last-text"
                    x={PAD_LEFT + plotW + 6}
                    y={scale.y(last.close) + 3.5}
                  >
                    {fmt.price(last.close)}
                  </text>
                </g>
              )}

              {/* crosshair */}
              {hover != null && bars[hover] && (
                <line
                  className="chart-cross"
                  x1={scale.x(hover)}
                  x2={scale.x(hover)}
                  y1={PAD_TOP}
                  y2={PAD_TOP + PRICE_H + VOLUME_H}
                />
              )}

              {/* time axis */}
              {bars.map((b, i) =>
                // Centre-anchored labels near the left edge get clipped, so
                // only draw one once there is room for half its width.
                i % labelStep(bars.length, plotW) === 0 && scale.x(i) > 26 ? (
                  <text
                    key={`t${b.time}`}
                    className="chart-axis"
                    x={scale.x(i)}
                    y={CHART_H - 5}
                    textAnchor="middle"
                  >
                    {axisTime(b.time, timeframe)}
                  </text>
                ) : null,
              )}
            </svg>
          )
        )}
      </div>

      <div className="chart-foot">
        <span>
          {symbol} · {timeframe} · {bars.length} candles
        </span>
        <span className="dim">
          {loading && bars.length ? "refreshing…" : `updated ${fmt.time(
            updatedAt ? new Date(updatedAt).toISOString() : null,
          )}`}
        </span>
      </div>
    </div>
  );
}
