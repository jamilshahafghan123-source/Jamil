/**
 * Indicator calculations.
 *
 * Pure functions over a bar array, kept out of components so they can be
 * memoised on the bars they were computed from. Recomputing a full history
 * on every tick is the usual reason a chart feels heavy; the callers
 * memoise on `bars`, so a poll that returns the same array costs nothing.
 *
 * Every series returns the same length as its input, with `null` where the
 * indicator has not warmed up. Returning a shorter array would force every
 * caller to track an offset, and an off-by-one there draws a moving average
 * against the wrong candles — a bug that looks like a trading signal.
 */

import type { Bar } from "./types";

export type Series = (number | null)[];

function sourceValues(bars: Bar[]): number[] {
  return bars.map((b) => b.close);
}

export function sma(bars: Bar[], period: number): Series {
  const src = sourceValues(bars);
  const out: Series = new Array(src.length).fill(null);
  if (period <= 0) return out;
  let sum = 0;
  for (let i = 0; i < src.length; i++) {
    sum += src[i];
    if (i >= period) sum -= src[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

export function ema(bars: Bar[], period: number): Series {
  const src = sourceValues(bars);
  const out: Series = new Array(src.length).fill(null);
  if (period <= 0 || src.length < period) return out;
  const k = 2 / (period + 1);
  // Seed with the SMA of the first `period` values, the conventional start.
  let prev = src.slice(0, period).reduce((a, b) => a + b, 0) / period;
  out[period - 1] = prev;
  for (let i = period; i < src.length; i++) {
    prev = src[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

export function rsi(bars: Bar[], period = 14): Series {
  const src = sourceValues(bars);
  const out: Series = new Array(src.length).fill(null);
  if (src.length <= period) return out;

  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const change = src[i] - src[i - 1];
    if (change >= 0) gain += change;
    else loss -= change;
  }
  gain /= period;
  loss /= period;
  // A period of no losses is RSI 100, not a division by zero.
  out[period] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);

  for (let i = period + 1; i < src.length; i++) {
    const change = src[i] - src[i - 1];
    gain = (gain * (period - 1) + Math.max(change, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-change, 0)) / period;
    out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  }
  return out;
}

export interface MacdResult {
  macd: Series;
  signal: Series;
  histogram: Series;
}

export function macd(
  bars: Bar[],
  fast = 12,
  slow = 26,
  signalPeriod = 9,
): MacdResult {
  const fastLine = ema(bars, fast);
  const slowLine = ema(bars, slow);
  const macdLine: Series = bars.map((_, i) =>
    fastLine[i] != null && slowLine[i] != null
      ? (fastLine[i] as number) - (slowLine[i] as number)
      : null,
  );

  // The signal line is an EMA of the MACD line, which only exists from the
  // slow period onward — so it is seeded from that offset, not from zero.
  const start = macdLine.findIndex((v) => v != null);
  const signal: Series = new Array(bars.length).fill(null);
  if (start >= 0 && bars.length - start > signalPeriod) {
    const k = 2 / (signalPeriod + 1);
    let prev = 0;
    for (let i = start; i < start + signalPeriod; i++) {
      prev += macdLine[i] as number;
    }
    prev /= signalPeriod;
    signal[start + signalPeriod - 1] = prev;
    for (let i = start + signalPeriod; i < bars.length; i++) {
      prev = (macdLine[i] as number) * k + prev * (1 - k);
      signal[i] = prev;
    }
  }

  const histogram: Series = bars.map((_, i) =>
    macdLine[i] != null && signal[i] != null
      ? (macdLine[i] as number) - (signal[i] as number)
      : null,
  );
  return { macd: macdLine, signal, histogram };
}

export interface BollingerResult {
  upper: Series;
  middle: Series;
  lower: Series;
}

export function bollinger(bars: Bar[], period = 20, deviations = 2): BollingerResult {
  const src = sourceValues(bars);
  const middle = sma(bars, period);
  const upper: Series = new Array(src.length).fill(null);
  const lower: Series = new Array(src.length).fill(null);

  for (let i = period - 1; i < src.length; i++) {
    const mean = middle[i];
    if (mean == null) continue;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) {
      variance += (src[j] - mean) ** 2;
    }
    const sd = Math.sqrt(variance / period);
    upper[i] = mean + deviations * sd;
    lower[i] = mean - deviations * sd;
  }
  return { upper, middle, lower };
}

/** Wilder's ATR. Uses true range, so a gap counts as movement. */
export function atr(bars: Bar[], period = 14): Series {
  const out: Series = new Array(bars.length).fill(null);
  if (bars.length <= period) return out;

  const trueRanges: number[] = [0];
  for (let i = 1; i < bars.length; i++) {
    const prevClose = bars[i - 1].close;
    trueRanges.push(
      Math.max(
        bars[i].high - bars[i].low,
        Math.abs(bars[i].high - prevClose),
        Math.abs(bars[i].low - prevClose),
      ),
    );
  }

  let value =
    trueRanges.slice(1, period + 1).reduce((a, b) => a + b, 0) / period;
  out[period] = value;
  for (let i = period + 1; i < bars.length; i++) {
    value = (value * (period - 1) + trueRanges[i]) / period;
    out[i] = value;
  }
  return out;
}

/**
 * VWAP over the loaded window.
 *
 * A true VWAP resets each session. The bars endpoint returns a rolling
 * window rather than session-delimited data, so this is a rolling VWAP over
 * what is loaded and is labelled that way in the UI rather than being
 * presented as the session figure it is not.
 */
export function vwap(bars: Bar[]): Series {
  const out: Series = new Array(bars.length).fill(null);
  let cumulativePV = 0;
  let cumulativeVolume = 0;
  for (let i = 0; i < bars.length; i++) {
    const typical = (bars[i].high + bars[i].low + bars[i].close) / 3;
    const volume = bars[i].tick_volume || 0;
    cumulativePV += typical * volume;
    cumulativeVolume += volume;
    out[i] = cumulativeVolume > 0 ? cumulativePV / cumulativeVolume : null;
  }
  return out;
}

/**
 * Tick volume, and its own moving average.
 *
 * MT5 reports tick volume — the number of price changes in the bar — not
 * traded contracts, because a retail forex/metals feed has no access to
 * exchange volume. It is a real measure of activity and is labelled as tick
 * volume everywhere it is shown, rather than being passed off as turnover.
 *
 * The average is what makes it readable: a raw count means little on its
 * own, but "this bar is running at twice its recent average" does.
 */
export function tickVolume(bars: Bar[]): Series {
  return bars.map((bar) => bar.tick_volume ?? null);
}

export function tickVolumeAverage(bars: Bar[], period = 20): Series {
  const out: Series = new Array(bars.length).fill(null);
  if (period <= 0) return out;
  let running = 0;
  for (let i = 0; i < bars.length; i++) {
    running += bars[i].tick_volume ?? 0;
    if (i >= period) running -= bars[i - period].tick_volume ?? 0;
    if (i >= period - 1) out[i] = running / period;
  }
  return out;
}

export type IndicatorKind =
  | "SMA"
  | "EMA"
  | "BOLLINGER"
  | "VWAP"
  | "RSI"
  | "MACD"
  | "ATR"
  | "VOLUME";

export interface IndicatorConfig {
  id: string;
  kind: IndicatorKind;
  period: number;
  enabled: boolean;
  colour: string;
}

/** Which indicators draw on the price chart rather than reading out below. */
export const OVERLAY_KINDS: IndicatorKind[] = ["SMA", "EMA", "BOLLINGER", "VWAP"];

export function isOverlay(kind: IndicatorKind): boolean {
  return OVERLAY_KINDS.includes(kind);
}

export const DEFAULT_PERIOD: Record<IndicatorKind, number> = {
  SMA: 20,
  EMA: 50,
  BOLLINGER: 20,
  VWAP: 0,
  RSI: 14,
  MACD: 12,
  ATR: 14,
  VOLUME: 20,
};

/** Last non-null value of a series, for the readout strip. */
export function latest(series: Series): number | null {
  for (let i = series.length - 1; i >= 0; i--) {
    if (series[i] != null) return series[i] as number;
  }
  return null;
}
