"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { price as fmtPrice } from "@/lib/format";
import type { Candle } from "@/lib/types";
import { ErrorNotice, Spinner } from "./ui";
import type { ApiClientError } from "@/lib/client";

const AXIS_WIDTH = 64;
const AXIS_HEIGHT = 22;
const PADDING_TOP = 10;

/** Canvas candlestick chart drawn straight from the bridge's MT5 candles. */
export default function CandleChart({
  candles,
  digits,
  loading,
  error,
  online,
  onRetry,
}: {
  candles: Candle[];
  digits: number;
  loading: boolean;
  error: ApiClientError | null;
  online: boolean;
  onRetry: () => void;
}) {
  const holderRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const holder = holderRef.current;
    if (!holder) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width, height });
    });
    observer.observe(holder);
    return () => observer.disconnect();
  }, []);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || size.width === 0 || size.height === 0) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(size.width * dpr);
    canvas.height = Math.floor(size.height * dpr);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    const styles = getComputedStyle(document.documentElement);
    const colors = {
      grid: styles.getPropertyValue("--border").trim() || "#23304a",
      text: styles.getPropertyValue("--muted").trim() || "#8496b3",
      up: styles.getPropertyValue("--up").trim() || "#26a69a",
      down: styles.getPropertyValue("--down").trim() || "#ef5350",
      accent: styles.getPropertyValue("--accent").trim() || "#4c8dff",
    };

    ctx.clearRect(0, 0, size.width, size.height);
    if (candles.length === 0) return;

    const plotWidth = size.width - AXIS_WIDTH;
    const plotHeight = size.height - AXIS_HEIGHT - PADDING_TOP;

    let low = Infinity;
    let high = -Infinity;
    for (const candle of candles) {
      if (candle.low < low) low = candle.low;
      if (candle.high > high) high = candle.high;
    }
    const pad = (high - low) * 0.06 || high * 0.001 || 1;
    low -= pad;
    high += pad;
    const span = high - low || 1;

    const yFor = (value: number) => PADDING_TOP + (1 - (value - low) / span) * plotHeight;
    const slot = plotWidth / candles.length;
    const bodyWidth = Math.max(1, Math.min(14, slot * 0.62));

    // Grid + price axis
    ctx.font = "11px ui-monospace, monospace";
    ctx.textBaseline = "middle";
    ctx.strokeStyle = colors.grid;
    ctx.fillStyle = colors.text;
    ctx.lineWidth = 1;
    const gridLines = 5;
    for (let i = 0; i <= gridLines; i += 1) {
      const value = low + (span * i) / gridLines;
      const y = Math.round(yFor(value)) + 0.5;
      ctx.globalAlpha = 0.45;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(plotWidth, y);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillText(value.toFixed(digits), plotWidth + 8, y);
    }

    // Time axis
    ctx.textBaseline = "top";
    const labelEvery = Math.max(1, Math.floor(candles.length / 6));
    for (let i = 0; i < candles.length; i += labelEvery) {
      const x = i * slot + slot / 2;
      const label = new Date(candles[i].time).toISOString().slice(5, 16).replace("T", " ");
      const width = ctx.measureText(label).width;
      if (x + width / 2 > plotWidth) continue;
      ctx.fillText(label, x - width / 2, size.height - AXIS_HEIGHT + 6);
    }

    // Candles
    candles.forEach((candle, index) => {
      const x = index * slot + slot / 2;
      const rising = candle.close >= candle.open;
      const color = rising ? colors.up : colors.down;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;

      ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, yFor(candle.high));
      ctx.lineTo(Math.round(x) + 0.5, yFor(candle.low));
      ctx.stroke();

      const top = yFor(Math.max(candle.open, candle.close));
      const bottom = yFor(Math.min(candle.open, candle.close));
      ctx.fillRect(x - bodyWidth / 2, top, bodyWidth, Math.max(1, bottom - top));
    });

    // Last price marker
    const last = candles[candles.length - 1];
    const lastY = yFor(last.close);
    ctx.strokeStyle = colors.accent;
    ctx.globalAlpha = 0.7;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(0, Math.round(lastY) + 0.5);
    ctx.lineTo(plotWidth, Math.round(lastY) + 0.5);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
    ctx.fillStyle = colors.accent;
    ctx.fillRect(plotWidth, lastY - 9, AXIS_WIDTH, 18);
    ctx.fillStyle = "#05122c";
    ctx.textBaseline = "middle";
    ctx.fillText(last.close.toFixed(digits), plotWidth + 6, lastY);

    // Crosshair
    if (hover != null && candles[hover]) {
      const x = hover * slot + slot / 2;
      ctx.strokeStyle = colors.text;
      ctx.globalAlpha = 0.55;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, PADDING_TOP);
      ctx.lineTo(Math.round(x) + 0.5, PADDING_TOP + plotHeight);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }
  }, [candles, digits, hover, size]);

  useEffect(() => {
    draw();
  }, [draw]);

  const onMove = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (candles.length === 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const plotWidth = rect.width - AXIS_WIDTH;
    if (x < 0 || x > plotWidth) {
      setHover(null);
      return;
    }
    const index = Math.min(candles.length - 1, Math.floor((x / plotWidth) * candles.length));
    setHover(index);
  };

  const active = hover != null ? candles[hover] : candles[candles.length - 1];

  return (
    <div className="chart-holder" ref={holderRef}>
      <canvas
        ref={canvasRef}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={`Candlestick chart, ${candles.length} candles from MetaTrader 5`}
      />

      {active ? (
        <div className="chart-readout">
          <span>O {fmtPrice(active.open, digits)}</span>
          <span>H {fmtPrice(active.high, digits)}</span>
          <span>L {fmtPrice(active.low, digits)}</span>
          <span>C {fmtPrice(active.close, digits)}</span>
          <span>{new Date(active.time).toISOString().slice(0, 16).replace("T", " ")}</span>
        </div>
      ) : null}

      {!online && candles.length === 0 ? (
        <div className="chart-overlay">
          <span className="muted">Chart data unavailable — MT5 Bridge Offline.</span>
        </div>
      ) : null}

      {online && loading && candles.length === 0 ? (
        <div className="chart-overlay">
          <span className="muted" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Spinner /> Loading MT5 candles…
          </span>
        </div>
      ) : null}

      {error && candles.length === 0 ? (
        <div className="chart-overlay">
          <div style={{ maxWidth: 460, width: "100%" }}>
            <ErrorNotice error={error} onRetry={onRetry} />
          </div>
        </div>
      ) : null}

      {online && !loading && !error && candles.length === 0 ? (
        <div className="chart-overlay">
          <span className="muted">No candles returned for this symbol and timeframe.</span>
        </div>
      ) : null}
    </div>
  );
}
