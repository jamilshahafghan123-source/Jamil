import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
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

export function TradingChart({
  bars,
  priceLines = [],
  zones = [],
  markers = [],
  height = 480,
}: {
  bars: Bar[];
  priceLines?: PriceLine[];
  zones?: ChartZone[];
  markers?: TradeMarker[];
  height?: number;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lines = useRef<ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]>([]);

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

    const resize = () => {
      if (holder.current) {
        instance.applyOptions({ width: holder.current.clientWidth });
      }
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(holder.current);

    return () => {
      observer.disconnect();
      instance.remove();
      chart.current = null;
      candles.current = null;
      lines.current = [];
    };
  }, [height]);

  // Data updates in place.
  useEffect(() => {
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
