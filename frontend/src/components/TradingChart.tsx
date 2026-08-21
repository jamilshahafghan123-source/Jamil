import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  type CandlestickData,
  type IChartApi,
  LineStyle,
  type ISeriesApi,
  type LineData,
  type LogicalRange,
  type SeriesMarker,
  type Time,
  createChart,
} from "lightweight-charts";
import type { Bar } from "../lib/types";

/**
 * Candlestick chart.
 *
 * LIBRARY: lightweight-charts 4.x, Apache-2.0. Chosen because it is
 * permissively licensed, actively maintained, and — unlike an embedded
 * public widget — takes our own data, so AI overlays, trade markers and
 * future order interaction are all possible. Its limitation is that it
 * draws series, not interactive shapes: user drawing tools have to be
 * built on top rather than switched on. That is a known cost, not a
 * surprise.
 *
 * ADAPTER BOUNDARY: this component takes `Bar[]` in the platform's own
 * shape and converts at the edge. Nothing outside this file knows the
 * library's types, so replacing it later is one file's work.
 *
 * Series are created once and updated in place. Rebuilding the chart on
 * every tick is what makes a terminal feel slow, and it throws away the
 * user's zoom and pan.
 */

export interface PriceLine {
  price: number;
  label: string;
  colour: string;
  dashed?: boolean;
}

export interface ChartZone {
  from: number;
  to: number;
  label: string;
  colour: string;
}

/** A computed overlay line: SMA, EMA, a Bollinger band, VWAP. */
export interface OverlaySeries {
  id: string;
  label: string;
  colour: string;
  /** Same length as `bars`; null where the indicator has not warmed up. */
  values: (number | null)[];
  dashed?: boolean;
}

export interface TradeMarker {
  time: string;
  side: "BUY" | "SELL";
  source: "MANUAL" | "AI_ASSIST" | "AI_AUTO";
  text?: string;
  exit?: boolean;
}

/** Source decides the marker's colour, so AI and manual never look alike. */
const SOURCE_COLOUR: Record<TradeMarker["source"], string> = {
  MANUAL: "#8ab4f8",
  AI_ASSIST: "#d9a441",
  AI_AUTO: "#b071e0",
};

function toSeconds(iso: string): Time {
  return (Math.floor(new Date(iso).getTime() / 1000) as unknown) as Time;
}

function toCandles(bars: Bar[]): CandlestickData<Time>[] {
  return bars
    .map((b) => ({
      time: toSeconds(b.time),
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }))
    // The library requires strictly ascending, de-duplicated times.
    .sort((a, b) => (a.time as number) - (b.time as number))
    .filter((bar, i, all) => i === 0 || bar.time !== all[i - 1].time);
}

/**
 * Coordinate bridge for the drawing layer.
 *
 * Drawings are stored in price and time, never pixels, so they survive a
 * resize, a zoom and a different screen. Converting between the two is the
 * chart's job — it owns the scales — so it is exposed here rather than
 * re-derived, which would drift the moment the user pans.
 */
export interface ChartCoordinates {
  priceToY: (price: number) => number | null;
  yToPrice: (y: number) => number | null;
  timeToX: (isoTime: string) => number | null;
  xToTime: (x: number) => string | null;
  /** Fires on every pan, zoom and resize so the overlay can repaint. */
  subscribe: (fn: () => void) => () => void;
}

export function TradingChart({
  bars,
  priceLines = [],
  zones = [],
  markers = [],
  overlays = [],
  height = 480,
  onCoordinates,
  onVisibleRangeChange,
}: {
  bars: Bar[];
  priceLines?: PriceLine[];
  zones?: ChartZone[];
  markers?: TradeMarker[];
  overlays?: OverlaySeries[];
  height?: number;
  onCoordinates?: (coords: ChartCoordinates | null) => void;
  /** Publishes the visible logical range so lower panes can follow it. */
  onVisibleRangeChange?: (range: LogicalRange | null) => void;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lines = useRef<ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]>([]);
  // Keyed by overlay id so a series is created once and updated in place;
  // removing and re-adding every poll would flicker and churn memory.
  const overlaySeries = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  // The coordinate bridge is built once with the chart, so it reads bars
  // through a ref rather than closing over a stale array.
  const barsRef = useRef<Bar[]>(bars);

  // Create once. Recreating on data change would discard zoom and pan.
  useEffect(() => {
    if (!holder.current) return;
    const instance = createChart(holder.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#0b0d10" },
        textColor: "#9aa3b0",
        fontSize: 11,
        // The library paints its vendor mark on the chart by default. The
        // Apache-2.0 licence does not require it, and carrying another
        // company's branding inside our terminal is the opposite of what a
        // J Gold AI chart should do.
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "rgba(35, 40, 51, 0.6)" },
        horzLines: { color: "rgba(35, 40, 51, 0.6)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "#646d7c", labelBackgroundColor: "#8a6a2c" },
        horzLine: { color: "#646d7c", labelBackgroundColor: "#8a6a2c" },
      },
      rightPriceScale: { borderColor: "#232833" },
      timeScale: { borderColor: "#232833", timeVisible: true, secondsVisible: false },
      handleScroll: true,
      handleScale: true,
    });
    const series = instance.addCandlestickSeries({
      upColor: "#3fb950",
      downColor: "#f4564a",
      wickUpColor: "#3fb950",
      wickDownColor: "#f4564a",
      borderVisible: false,
    });
    chart.current = instance;
    candles.current = series;

    const listeners = new Set<() => void>();
    const notify = () => listeners.forEach((fn) => fn());

    // Times are SNAPPED TO REAL BARS in both directions.
    //
    // timeToCoordinate only maps times that exactly match a data point, so
    // a click landing between two candles yields a time the library can
    // never project back — the drawing vanishes on the next reload. Snapping
    // costs sub-candle precision and buys an annotation that stays put
    // across reloads, timeframe switches and zoom, which is the trade a
    // chart annotation should make anyway.
    const nearestBarTime = (targetSeconds: number): string | null => {
      const list = barsRef.current;
      if (list.length === 0) return null;
      let best = list[0];
      let bestGap = Infinity;
      for (const bar of list) {
        const gap = Math.abs(
          Math.floor(new Date(bar.time).getTime() / 1000) - targetSeconds,
        );
        if (gap < bestGap) {
          bestGap = gap;
          best = bar;
        }
      }
      return best.time;
    };

    onCoordinates?.({
      priceToY: (price) => series.priceToCoordinate(price) as number | null,
      yToPrice: (y) => series.coordinateToPrice(y) as number | null,
      timeToX: (iso) => {
        const scale = instance.timeScale();
        const exact = scale.timeToCoordinate(toSeconds(iso)) as number | null;
        if (exact != null) return exact;
        // A stored time whose bar has scrolled out of the loaded window.
        const snapped = nearestBarTime(
          Math.floor(new Date(iso).getTime() / 1000),
        );
        return snapped == null
          ? null
          : (scale.timeToCoordinate(toSeconds(snapped)) as number | null);
      },
      xToTime: (x) => {
        const t = instance.timeScale().coordinateToTime(x);
        if (t == null) return null;
        return nearestBarTime(t as number);
      },
      subscribe: (fn) => {
        listeners.add(fn);
        return () => listeners.delete(fn);
      },
    });

    instance.timeScale().subscribeVisibleLogicalRangeChange(notify);

    // Lower panes follow this range. Published separately from `notify`
    // so the overlay repaint and the pane sync stay independent.
    const publishRange = (range: LogicalRange | null) =>
      onVisibleRangeChange?.(range);
    instance.timeScale().subscribeVisibleLogicalRangeChange(publishRange);

    const resize = () => {
      if (holder.current) {
        instance.applyOptions({ width: holder.current.clientWidth });
        notify();
      }
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(holder.current);

    return () => {
      observer.disconnect();
      // remove() disposes every series with the chart, so the overlay map
      // is cleared rather than iterated — touching a disposed series after
      // this throws.
      instance.remove();
      chart.current = null;
      candles.current = null;
      lines.current = [];
      overlaySeries.current.clear();
      listeners.clear();
      // Tell the overlay its coordinates are gone; calling into a disposed
      // chart throws, and a stale bridge is exactly how that happens.
      onCoordinates?.(null);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  // Data updates in place.
  useEffect(() => {
    barsRef.current = bars;
    if (!candles.current) return;
    candles.current.setData(toCandles(bars));
  }, [bars]);

  // Price lines: entry, stop, target, AI levels. Removed and re-added as a
  // set, since the library has no diffing API for them.
  useEffect(() => {
    const series = candles.current;
    if (!series) return;
    lines.current.forEach((line) => series.removePriceLine(line));
    lines.current = [...priceLines, ...zones.flatMap((z) => [
      { price: z.from, label: `${z.label} ▲`, colour: z.colour, dashed: true },
      { price: z.to, label: `${z.label} ▼`, colour: z.colour, dashed: true },
    ])].map((l) =>
      series.createPriceLine({
        price: l.price,
        color: l.colour,
        lineWidth: 1,
        lineStyle: l.dashed ? 2 : 0,
        axisLabelVisible: true,
        title: l.label,
      }),
    );
  }, [priceLines, zones]);

  // Overlays: create once per id, update in place, drop what disappeared.
  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    const live = new Set(overlays.map((o) => o.id));

    for (const [id, series] of overlaySeries.current) {
      if (!live.has(id)) {
        instance.removeSeries(series);
        overlaySeries.current.delete(id);
      }
    }

    for (const overlay of overlays) {
      let series = overlaySeries.current.get(overlay.id);
      if (!series) {
        series = instance.addLineSeries({
          color: overlay.colour,
          lineWidth: 1,
          lineStyle: overlay.dashed ? LineStyle.Dashed : LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        overlaySeries.current.set(overlay.id, series);
      } else {
        series.applyOptions({ color: overlay.colour });
      }
      const data: LineData<Time>[] = [];
      for (let i = 0; i < bars.length && i < overlay.values.length; i++) {
        const value = overlay.values[i];
        // Gaps are omitted rather than zero-filled: a zero would draw a
        // line to the bottom of the chart and look like a crash.
        if (value == null) continue;
        data.push({ time: toSeconds(bars[i].time), value });
      }
      series.setData(
        data
          .sort((a, b) => (a.time as number) - (b.time as number))
          .filter((d, i, all) => i === 0 || d.time !== all[i - 1].time),
      );
    }
  }, [overlays, bars]);

  useEffect(() => {
    if (!candles.current) return;
    const marks: SeriesMarker<Time>[] = markers.map((m) => ({
      time: toSeconds(m.time),
      position: m.side === "BUY" ? "belowBar" : "aboveBar",
      shape: m.exit ? "circle" : m.side === "BUY" ? "arrowUp" : "arrowDown",
      color: SOURCE_COLOUR[m.source],
      text: m.text ?? `${m.source === "MANUAL" ? "" : "AI "}${m.side}`,
    }));
    candles.current.setMarkers(marks);
  }, [markers]);

  return <div ref={holder} className="jg-chart" />;
}
