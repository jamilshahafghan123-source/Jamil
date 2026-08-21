import { useEffect, useRef } from "react";
import {
  ColorType, LineStyle, createChart,
  type IChartApi, type ISeriesApi, type LogicalRange, type UTCTimestamp,
} from "lightweight-charts";
import type { Bar } from "../lib/types";

/**
 * A lower indicator pane (section 28).
 *
 * lightweight-charts 4.x has no multi-pane API — `addPane` arrived in
 * v5 — so rather than upgrade the chart engine mid-project, or fake a
 * pane by cramming an oscillator onto the price scale where its 0-100
 * range would flatten the candles, each pane is its own small chart
 * instance stacked beneath the main one with its OWN price scale.
 *
 * The panes are kept in step by sharing the main chart's visible logical
 * range: whoever moves publishes, everyone else follows. `syncing` guards
 * the echo, since applying a range fires the same event that delivered it
 * and two charts would otherwise push each other back and forth forever.
 *
 * The honest limitation, reported rather than hidden: a pane cannot be
 * dragged to resize, and its height is set by the caller.
 */

export interface PaneSeries {
  id: string;
  label: string;
  colour: string;
  values: (number | null)[];
  /** Draw as a histogram (MACD, volume) rather than a line. */
  histogram?: boolean;
  dashed?: boolean;
}

export interface PaneGuide {
  value: number;
  colour?: string;
}

export function IndicatorPane({
  bars,
  series,
  guides = [],
  title,
  height = 110,
  onRangeChange,
  externalRange,
  onRemove,
}: {
  bars: Bar[];
  series: PaneSeries[];
  /** Horizontal reference lines: RSI 70/30, MACD zero. */
  guides?: PaneGuide[];
  title: string;
  height?: number;
  onRangeChange?: (range: LogicalRange | null) => void;
  externalRange?: LogicalRange | null;
  onRemove?: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const lines = useRef<Map<string, ISeriesApi<"Line" | "Histogram">>>(new Map());
  const syncing = useRef(false);

  useEffect(() => {
    if (!host.current) return;
    const instance = createChart(host.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8b93a1",
        fontSize: 10,
        // Same reason as the main chart: no other company's mark inside
        // a J Gold AI terminal.
        attributionLogo: false,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      rightPriceScale: { borderColor: "#23262d", scaleMargins: { top: 0.12, bottom: 0.08 } },
      // The main chart already shows the time axis; repeating it under
      // every pane wastes the vertical space the pane exists to use.
      timeScale: { visible: false, borderColor: "#23262d" },
      crosshair: { horzLine: { visible: false } },
      handleScale: true,
      handleScroll: true,
    });
    chart.current = instance;

    const publish = (range: LogicalRange | null) => {
      if (syncing.current) return;
      onRangeChange?.(range);
    };
    instance.timeScale().subscribeVisibleLogicalRangeChange(publish);

    const resize = () => {
      if (host.current) {
        instance.applyOptions({ width: host.current.clientWidth });
      }
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(host.current);

    return () => {
      observer.disconnect();
      instance.timeScale().unsubscribeVisibleLogicalRangeChange(publish);
      // remove() disposes every series with the chart, so the map must be
      // cleared or the next mount reuses handles pointing at nothing.
      instance.remove();
      lines.current.clear();
      chart.current = null;
    };
  }, [height, onRangeChange]);

  // Follow the main chart. The guard stops the echo from bouncing back.
  useEffect(() => {
    const instance = chart.current;
    if (!instance || !externalRange) return;
    syncing.current = true;
    try {
      instance.timeScale().setVisibleLogicalRange(externalRange);
    } catch {
      /* a range from before this pane had data is simply ignored */
    }
    syncing.current = false;
  }, [externalRange]);

  // Series: created once per id, updated in place, dropped when gone.
  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;

    const live = new Set(series.map((s) => s.id));
    for (const [id, handle] of lines.current) {
      if (!live.has(id)) {
        instance.removeSeries(handle);
        lines.current.delete(id);
      }
    }

    for (const entry of series) {
      let handle = lines.current.get(entry.id);
      if (!handle) {
        handle = entry.histogram
          ? instance.addHistogramSeries({
              color: entry.colour, priceLineVisible: false,
              lastValueVisible: false,
            })
          : instance.addLineSeries({
              color: entry.colour, lineWidth: 1,
              lineStyle: entry.dashed ? LineStyle.Dashed : LineStyle.Solid,
              priceLineVisible: false, lastValueVisible: true,
            });
        lines.current.set(entry.id, handle);
      } else {
        handle.applyOptions({ color: entry.colour });
      }

      const points: { time: UTCTimestamp; value: number }[] = [];
      for (let i = 0; i < bars.length && i < entry.values.length; i++) {
        const value = entry.values[i];
        if (value == null || !Number.isFinite(value)) continue;
        points.push({
          time: Math.floor(new Date(bars[i].time).getTime() / 1000) as UTCTimestamp,
          value,
        });
      }
      handle.setData(points);
    }
  }, [series, bars]);

  // Guides are price lines on the first series, which is where they belong
  // numerically — an RSI 70 line means nothing on a MACD scale.
  useEffect(() => {
    const first = series[0] && lines.current.get(series[0].id);
    if (!first) return;
    const created = guides.map((guide) =>
      first.createPriceLine({
        price: guide.value,
        color: guide.colour ?? "rgba(255,255,255,0.18)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: false,
        title: "",
      }),
    );
    return () => created.forEach((line) => first.removePriceLine(line));
  }, [guides, series]);

  return (
    <div className="jg-pane">
      <div className="jg-pane-head">
        <span className="jg-pane-title">{title}</span>
        {series.map((s) => (
          <span key={s.id} className="jg-pane-key" style={{ color: s.colour }}>
            {s.label}
          </span>
        ))}
        <div className="jg-spacer" />
        {onRemove && (
          <button type="button" className="jg-pane-close" onClick={onRemove}
                  aria-label={`Remove ${title} pane`} title="Remove pane">
            ×
          </button>
        )}
      </div>
      <div ref={host} className="jg-pane-canvas" />
    </div>
  );
}
