import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineStyle,
  createChart,
} from 'lightweight-charts';
import type {
  CandlestickData,
  HistogramData,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  Time,
  UTCTimestamp,
} from 'lightweight-charts';
import type { AiAnalysis, Candle } from '@/types';

const COLORS = {
  background: 'transparent',
  text: '#6c778c',
  grid: 'rgba(255,255,255,0.035)',
  border: '#1a2330',
  up: '#21c98a',
  down: '#f2555a',
  upWick: '#34d99b',
  downWick: '#ff7276',
  volumeUp: 'rgba(33,201,138,0.32)',
  volumeDown: 'rgba(242,85,90,0.32)',
  entry: '#e5b45f',
  stop: '#f2555a',
  target: '#21c98a',
};

export interface CandleChartProps {
  candles: Candle[];
  /** When supplied, entry / stop / target levels are drawn as price lines. */
  analysis?: AiAnalysis | null;
  showVolume?: boolean;
  showLevels?: boolean;
  /** Increment to re-fit the visible range (used by the "reset zoom" button). */
  fitSignal?: number;
  height?: number;
  className?: string;
}

/**
 * Interactive candlestick chart (zoom, pan, crosshair, optional volume pane).
 *
 * The chart instance is created once and then fed data imperatively, so live
 * ticks update the last candle without tearing down the canvas.
 */
export function CandleChart({
  candles,
  analysis,
  showVolume = true,
  showLevels = true,
  fitSignal = 0,
  height = 460,
  className,
}: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const hasFittedRef = useRef(false);

  // --- create the chart once -------------------------------------------
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: COLORS.background },
        textColor: COLORS.text,
        fontFamily: "'Inter', system-ui, sans-serif",
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: COLORS.grid },
        horzLines: { color: COLORS.grid },
      },
      rightPriceScale: {
        borderColor: COLORS.border,
        scaleMargins: { top: 0.08, bottom: showVolume ? 0.26 : 0.08 },
      },
      timeScale: {
        borderColor: COLORS.border,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 6,
        barSpacing: 8,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(229,180,95,0.5)',
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: '#cf9a3c',
        },
        horzLine: {
          color: 'rgba(229,180,95,0.5)',
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: '#cf9a3c',
        },
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
      autoSize: true,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: COLORS.up,
      downColor: COLORS.down,
      borderUpColor: COLORS.up,
      borderDownColor: COLORS.down,
      wickUpColor: COLORS.upWick,
      wickDownColor: COLORS.downWick,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;

    if (showVolume) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });
      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
        borderVisible: false,
      });
      volumeSeriesRef.current = volumeSeries;
    }

    return () => {
      priceLinesRef.current = [];
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      chartRef.current = null;
      hasFittedRef.current = false;
      chart.remove();
    };
  }, [showVolume]);

  // --- feed candles ------------------------------------------------------
  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    const chart = chartRef.current;
    if (!candleSeries || !chart || candles.length === 0) return;

    const candleData: CandlestickData<Time>[] = candles.map((c) => ({
      time: c.time as UTCTimestamp,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    candleSeries.setData(candleData);

    if (volumeSeriesRef.current) {
      const volumeData: HistogramData<Time>[] = candles.map((c) => ({
        time: c.time as UTCTimestamp,
        value: c.volume,
        color: c.close >= c.open ? COLORS.volumeUp : COLORS.volumeDown,
      }));
      volumeSeriesRef.current.setData(volumeData);
    }

    // Only auto-fit the first time so the user's zoom/pan survives updates.
    if (!hasFittedRef.current) {
      chart.timeScale().fitContent();
      hasFittedRef.current = true;
    }
  }, [candles]);

  // --- AI levels as price lines -----------------------------------------
  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;

    for (const line of priceLinesRef.current) series.removePriceLine(line);
    priceLinesRef.current = [];

    if (!showLevels || !analysis) return;

    const entryMid = (analysis.entryZone.from + analysis.entryZone.to) / 2;
    const lines: { price: number; color: string; title: string }[] = [
      { price: entryMid, color: COLORS.entry, title: 'AI entry' },
      { price: analysis.stopLoss, color: COLORS.stop, title: 'AI stop' },
      ...analysis.takeProfit.map((price, i) => ({
        price,
        color: COLORS.target,
        title: `AI TP${i + 1}`,
      })),
    ];

    priceLinesRef.current = lines.map(({ price, color, title }) =>
      series.createPriceLine({
        price,
        color,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title,
      }),
    );
  }, [analysis, showLevels]);

  // --- reset zoom on demand ---------------------------------------------
  useEffect(() => {
    if (fitSignal === 0) return;
    chartRef.current?.timeScale().fitContent();
  }, [fitSignal]);

  return <div ref={containerRef} className={className} style={{ height }} />;
}
