/**
 * Small, dependency-free technical indicator helpers.
 *
 * These power the demo AI analysis. When the backend AI service is connected
 * the analysis arrives pre-computed and these are only used for chart overlays.
 */
import type { Candle } from '@/types';

export function sma(values: number[], period: number): number[] {
  const out: number[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i += 1) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    out.push(i >= period - 1 ? sum / period : Number.NaN);
  }
  return out;
}

export function ema(values: number[], period: number): number[] {
  const out: number[] = [];
  const k = 2 / (period + 1);
  let prev = Number.NaN;
  for (let i = 0; i < values.length; i += 1) {
    if (i < period - 1) {
      out.push(Number.NaN);
      continue;
    }
    if (Number.isNaN(prev)) {
      const seed = values.slice(0, period).reduce((a, b) => a + b, 0) / period;
      prev = seed;
    } else {
      prev = values[i] * k + prev * (1 - k);
    }
    out.push(prev);
  }
  return out;
}

/** Wilder's RSI. Returns NaN until `period` closes are available. */
export function rsi(values: number[], period = 14): number[] {
  const out: number[] = new Array(values.length).fill(Number.NaN);
  if (values.length <= period) return out;

  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i += 1) {
    const change = values[i] - values[i - 1];
    if (change >= 0) avgGain += change;
    else avgLoss -= change;
  }
  avgGain /= period;
  avgLoss /= period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

  for (let i = period + 1; i < values.length; i += 1) {
    const change = values[i] - values[i - 1];
    const gain = change > 0 ? change : 0;
    const loss = change < 0 ? -change : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

/** Average True Range — used to size the demo stop loss sensibly. */
export function atr(candles: Candle[], period = 14): number {
  if (candles.length < 2) return 0;
  const trs: number[] = [];
  for (let i = 1; i < candles.length; i += 1) {
    const c = candles[i];
    const prevClose = candles[i - 1].close;
    trs.push(
      Math.max(c.high - c.low, Math.abs(c.high - prevClose), Math.abs(c.low - prevClose)),
    );
  }
  const window = trs.slice(-period);
  return window.reduce((a, b) => a + b, 0) / window.length;
}

export interface SwingLevel {
  price: number;
  /** How many independent swings clustered around this price. */
  touches: number;
}

/**
 * Detects swing highs/lows with a fractal window, then clusters nearby swings
 * so the panel shows a handful of meaningful levels rather than dozens.
 */
export function swingLevels(
  candles: Candle[],
  kind: 'high' | 'low',
  lookback = 3,
  tolerance = 0.0015,
): SwingLevel[] {
  const pivots: number[] = [];
  for (let i = lookback; i < candles.length - lookback; i += 1) {
    const value = kind === 'high' ? candles[i].high : candles[i].low;
    let isPivot = true;
    for (let j = i - lookback; j <= i + lookback; j += 1) {
      if (j === i) continue;
      const other = kind === 'high' ? candles[j].high : candles[j].low;
      if (kind === 'high' ? other > value : other < value) {
        isPivot = false;
        break;
      }
    }
    if (isPivot) pivots.push(value);
  }

  const clusters: { sum: number; count: number; price: number }[] = [];
  for (const price of pivots) {
    const hit = clusters.find((c) => Math.abs(c.price - price) / c.price <= tolerance);
    if (hit) {
      hit.sum += price;
      hit.count += 1;
      hit.price = hit.sum / hit.count;
    } else {
      clusters.push({ sum: price, count: 1, price });
    }
  }

  return clusters
    .map((c) => ({ price: c.price, touches: c.count }))
    .sort((a, b) => b.touches - a.touches || (kind === 'high' ? a.price - b.price : b.price - a.price));
}

export function lastFinite(values: number[]): number {
  for (let i = values.length - 1; i >= 0; i -= 1) {
    if (Number.isFinite(values[i])) return values[i];
  }
  return Number.NaN;
}
