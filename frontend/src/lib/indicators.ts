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

/**
 * Weighted moving average: linear weights, heaviest on the newest bar.
 */
export function wma(bars: Bar[], period: number): Series {
  const out: Series = new Array(bars.length).fill(null);
  if (period <= 0) return out;
  const divisor = (period * (period + 1)) / 2;
  for (let i = period - 1; i < bars.length; i++) {
    let total = 0;
    for (let k = 0; k < period; k++) {
      total += bars[i - period + 1 + k].close * (k + 1);
    }
    out[i] = total / divisor;
  }
  return out;
}

/**
 * Hull moving average: WMA(2*WMA(n/2) - WMA(n)) over sqrt(n).
 *
 * Built from the WMA above rather than approximated, so it keeps the
 * responsiveness that is the whole reason to choose it.
 */
export function hma(bars: Bar[], period: number): Series {
  const half = Math.max(1, Math.round(period / 2));
  const root = Math.max(1, Math.round(Math.sqrt(period)));
  const fast = wma(bars, half);
  const slow = wma(bars, period);
  const raw: Bar[] = bars.map((bar, i) => ({
    ...bar,
    close: fast[i] != null && slow[i] != null
      ? 2 * (fast[i] as number) - (slow[i] as number)
      : NaN,
  }));
  const smoothed = wma(raw, root);
  return smoothed.map((v) => (v == null || Number.isNaN(v) ? null : v));
}

/** Volume-weighted moving average, using tick volume as the weight. */
export function vwma(bars: Bar[], period: number): Series {
  const out: Series = new Array(bars.length).fill(null);
  if (period <= 0) return out;
  for (let i = period - 1; i < bars.length; i++) {
    let priceVolume = 0;
    let volume = 0;
    for (let k = i - period + 1; k <= i; k++) {
      const v = bars[k].tick_volume ?? 0;
      priceVolume += bars[k].close * v;
      volume += v;
    }
    out[i] = volume > 0 ? priceVolume / volume : null;
  }
  return out;
}

/** Donchian channel: the highest high and lowest low of the last n bars. */
export function donchian(bars: Bar[], period: number): {
  upper: Series; middle: Series; lower: Series;
} {
  const upper: Series = new Array(bars.length).fill(null);
  const lower: Series = new Array(bars.length).fill(null);
  const middle: Series = new Array(bars.length).fill(null);
  for (let i = period - 1; i < bars.length; i++) {
    let high = -Infinity;
    let low = Infinity;
    for (let k = i - period + 1; k <= i; k++) {
      high = Math.max(high, bars[k].high);
      low = Math.min(low, bars[k].low);
    }
    upper[i] = high;
    lower[i] = low;
    middle[i] = (high + low) / 2;
  }
  return { upper, middle, lower };
}

/** Keltner channel: an EMA centre with ATR-scaled bands. */
export function keltner(bars: Bar[], period = 20, multiplier = 2): {
  upper: Series; middle: Series; lower: Series;
} {
  const middle = ema(bars, period);
  const range = atr(bars, period);
  const upper: Series = middle.map((m, i) =>
    m != null && range[i] != null ? m + multiplier * (range[i] as number) : null);
  const lower: Series = middle.map((m, i) =>
    m != null && range[i] != null ? m - multiplier * (range[i] as number) : null);
  return { upper, middle, lower };
}

/**
 * Supertrend: an ATR band that flips side when price closes through it.
 *
 * The band ratchets — it only ever tightens towards price while the trend
 * holds — which is what stops it whipsawing on every bar.
 */
export function supertrend(bars: Bar[], period = 10, multiplier = 3): {
  line: Series; direction: (1 | -1 | null)[];
} {
  const range = atr(bars, period);
  const line: Series = new Array(bars.length).fill(null);
  const direction: (1 | -1 | null)[] = new Array(bars.length).fill(null);
  let upper = Infinity;
  let lower = -Infinity;
  let trend: 1 | -1 = 1;

  for (let i = 0; i < bars.length; i++) {
    const a = range[i];
    if (a == null) continue;
    const mid = (bars[i].high + bars[i].low) / 2;
    const rawUpper = mid + multiplier * a;
    const rawLower = mid - multiplier * a;
    const prevClose = i > 0 ? bars[i - 1].close : bars[i].close;

    upper = rawUpper < upper || prevClose > upper ? rawUpper : upper;
    lower = rawLower > lower || prevClose < lower ? rawLower : lower;

    if (bars[i].close > upper) trend = 1;
    else if (bars[i].close < lower) trend = -1;

    direction[i] = trend;
    line[i] = trend === 1 ? lower : upper;
  }
  return { line, direction };
}

/** Stochastic oscillator: where close sits in the recent high-low range. */
export function stochastic(bars: Bar[], period = 14, smooth = 3): {
  k: Series; d: Series;
} {
  const k: Series = new Array(bars.length).fill(null);
  for (let i = period - 1; i < bars.length; i++) {
    let high = -Infinity;
    let low = Infinity;
    for (let n = i - period + 1; n <= i; n++) {
      high = Math.max(high, bars[n].high);
      low = Math.min(low, bars[n].low);
    }
    // A flat range would divide by zero; the midpoint is the honest answer.
    k[i] = high === low ? 50 : ((bars[i].close - low) / (high - low)) * 100;
  }
  const d: Series = new Array(bars.length).fill(null);
  for (let i = 0; i < k.length; i++) {
    const window = k.slice(Math.max(0, i - smooth + 1), i + 1)
      .filter((v): v is number => v != null);
    if (window.length === smooth) {
      d[i] = window.reduce((a, b) => a + b, 0) / smooth;
    }
  }
  return { k, d };
}

/** Commodity Channel Index, on the typical price. */
export function cci(bars: Bar[], period = 20): Series {
  const out: Series = new Array(bars.length).fill(null);
  const typical = bars.map((b) => (b.high + b.low + b.close) / 3);
  for (let i = period - 1; i < bars.length; i++) {
    const window = typical.slice(i - period + 1, i + 1);
    const mean = window.reduce((a, b) => a + b, 0) / period;
    const deviation =
      window.reduce((a, b) => a + Math.abs(b - mean), 0) / period;
    out[i] = deviation === 0 ? 0 : (typical[i] - mean) / (0.015 * deviation);
  }
  return out;
}

/** Rate of change, as a percentage of the price n bars ago. */
export function roc(bars: Bar[], period = 12): Series {
  return bars.map((bar, i) => {
    if (i < period) return null;
    const past = bars[i - period].close;
    return past === 0 ? null : ((bar.close - past) / past) * 100;
  });
}

/** Williams %R: the stochastic's mirror, on a -100..0 scale. */
export function williamsR(bars: Bar[], period = 14): Series {
  const out: Series = new Array(bars.length).fill(null);
  for (let i = period - 1; i < bars.length; i++) {
    let high = -Infinity;
    let low = Infinity;
    for (let n = i - period + 1; n <= i; n++) {
      high = Math.max(high, bars[n].high);
      low = Math.min(low, bars[n].low);
    }
    out[i] = high === low ? -50 : ((high - bars[i].close) / (high - low)) * -100;
  }
  return out;
}

/**
 * Wilder's ADX with its two directional components.
 *
 * ADX measures trend STRENGTH and says nothing about direction; +DI and
 * -DI carry that, which is why all three are returned together rather
 * than ADX being read as a signal on its own.
 */
export function adx(bars: Bar[], period = 14): {
  adx: Series; plusDI: Series; minusDI: Series;
} {
  const n = bars.length;
  const adxOut: Series = new Array(n).fill(null);
  const plusDI: Series = new Array(n).fill(null);
  const minusDI: Series = new Array(n).fill(null);
  if (n <= period * 2) return { adx: adxOut, plusDI, minusDI };

  const plusDM: number[] = [0];
  const minusDM: number[] = [0];
  const trueRange: number[] = [0];
  for (let i = 1; i < n; i++) {
    const up = bars[i].high - bars[i - 1].high;
    const down = bars[i - 1].low - bars[i].low;
    plusDM.push(up > down && up > 0 ? up : 0);
    minusDM.push(down > up && down > 0 ? down : 0);
    trueRange.push(Math.max(
      bars[i].high - bars[i].low,
      Math.abs(bars[i].high - bars[i - 1].close),
      Math.abs(bars[i].low - bars[i - 1].close),
    ));
  }

  const smooth = (values: number[]) => {
    const out: number[] = new Array(n).fill(0);
    let total = values.slice(1, period + 1).reduce((a, b) => a + b, 0);
    out[period] = total;
    for (let i = period + 1; i < n; i++) {
      total = total - total / period + values[i];
      out[i] = total;
    }
    return out;
  };

  const sTR = smooth(trueRange);
  const sPlus = smooth(plusDM);
  const sMinus = smooth(minusDM);

  const dx: number[] = new Array(n).fill(0);
  for (let i = period; i < n; i++) {
    if (sTR[i] === 0) continue;
    const p = (sPlus[i] / sTR[i]) * 100;
    const m = (sMinus[i] / sTR[i]) * 100;
    plusDI[i] = p;
    minusDI[i] = m;
    dx[i] = p + m === 0 ? 0 : (Math.abs(p - m) / (p + m)) * 100;
  }

  let running = dx.slice(period, period * 2).reduce((a, b) => a + b, 0) / period;
  adxOut[period * 2 - 1] = running;
  for (let i = period * 2; i < n; i++) {
    running = (running * (period - 1) + dx[i]) / period;
    adxOut[i] = running;
  }
  return { adx: adxOut, plusDI, minusDI };
}

/** On-balance volume, signed by the close-to-close direction. */
export function obv(bars: Bar[]): Series {
  const out: Series = new Array(bars.length).fill(null);
  let total = 0;
  for (let i = 0; i < bars.length; i++) {
    if (i > 0) {
      const v = bars[i].tick_volume ?? 0;
      if (bars[i].close > bars[i - 1].close) total += v;
      else if (bars[i].close < bars[i - 1].close) total -= v;
    }
    out[i] = total;
  }
  return out;
}

/** Money Flow Index: a volume-weighted RSI on the typical price. */
export function mfi(bars: Bar[], period = 14): Series {
  const out: Series = new Array(bars.length).fill(null);
  const typical = bars.map((b) => (b.high + b.low + b.close) / 3);
  for (let i = period; i < bars.length; i++) {
    let positive = 0;
    let negative = 0;
    for (let k = i - period + 1; k <= i; k++) {
      const flow = typical[k] * (bars[k].tick_volume ?? 0);
      if (typical[k] > typical[k - 1]) positive += flow;
      else if (typical[k] < typical[k - 1]) negative += flow;
    }
    out[i] = negative === 0 ? 100 : 100 - 100 / (1 + positive / negative);
  }
  return out;
}

/** Standard deviation of closes — the raw volatility measure. */
export function standardDeviation(bars: Bar[], period = 20): Series {
  const out: Series = new Array(bars.length).fill(null);
  for (let i = period - 1; i < bars.length; i++) {
    const window = bars.slice(i - period + 1, i + 1).map((b) => b.close);
    const mean = window.reduce((a, b) => a + b, 0) / period;
    const variance =
      window.reduce((a, b) => a + (b - mean) ** 2, 0) / period;
    out[i] = Math.sqrt(variance);
  }
  return out;
}

/** Classic floor-trader pivots from the previous bar's range. */
export function pivotPoints(bars: Bar[]): {
  pivot: number; r1: number; r2: number; s1: number; s2: number;
} | null {
  if (bars.length < 2) return null;
  const previous = bars[bars.length - 2];
  const pivot = (previous.high + previous.low + previous.close) / 3;
  return {
    pivot,
    r1: 2 * pivot - previous.low,
    r2: pivot + (previous.high - previous.low),
    s1: 2 * pivot - previous.high,
    s2: pivot - (previous.high - previous.low),
  };
}

/**
 * Parabolic SAR.
 *
 * The acceleration factor steps only when a NEW extreme is made, and
 * resets on a flip. Stepping it every bar — the common shortcut — makes
 * the dots converge far too quickly and flips the trend on noise.
 */
export function parabolicSAR(bars: Bar[], step = 0.02, max = 0.2): {
  sar: Series; rising: (boolean | null)[];
} {
  const sar: Series = new Array(bars.length).fill(null);
  const rising: (boolean | null)[] = new Array(bars.length).fill(null);
  if (bars.length < 3) return { sar, rising };

  let up = bars[1].close >= bars[0].close;
  let acceleration = step;
  let extreme = up ? bars[1].high : bars[1].low;
  let current = up ? bars[0].low : bars[0].high;

  for (let i = 2; i < bars.length; i++) {
    current = current + acceleration * (extreme - current);

    // SAR may never enter the previous two bars' range.
    if (up) {
      current = Math.min(current, bars[i - 1].low, bars[i - 2].low);
    } else {
      current = Math.max(current, bars[i - 1].high, bars[i - 2].high);
    }

    const flipped = up ? bars[i].low < current : bars[i].high > current;
    if (flipped) {
      up = !up;
      current = extreme;
      extreme = up ? bars[i].high : bars[i].low;
      acceleration = step;
    } else if (up && bars[i].high > extreme) {
      extreme = bars[i].high;
      acceleration = Math.min(acceleration + step, max);
    } else if (!up && bars[i].low < extreme) {
      extreme = bars[i].low;
      acceleration = Math.min(acceleration + step, max);
    }

    sar[i] = current;
    rising[i] = up;
  }
  return { sar, rising };
}

/**
 * Ichimoku Kinko Hyo.
 *
 * The two leading spans are returned UNSHIFTED, with `displacement` saying
 * how far forward they belong. Shifting them here would silently align
 * cloud values with the wrong bars; the caller that draws them knows how
 * to offset, and one that only reads the latest value must not be handed
 * a future value as if it were current.
 */
export function ichimoku(
  bars: Bar[], conversion = 9, base = 26, spanB = 52,
): {
  conversion: Series; base: Series; spanA: Series; spanB: Series;
  lagging: Series; displacement: number;
} {
  const midpoint = (period: number, index: number): number | null => {
    if (index < period - 1) return null;
    let high = -Infinity;
    let low = Infinity;
    for (let k = index - period + 1; k <= index; k++) {
      high = Math.max(high, bars[k].high);
      low = Math.min(low, bars[k].low);
    }
    return (high + low) / 2;
  };

  const conv: Series = bars.map((_, i) => midpoint(conversion, i));
  const baseLine: Series = bars.map((_, i) => midpoint(base, i));
  const spanA: Series = bars.map((_, i) =>
    conv[i] != null && baseLine[i] != null
      ? ((conv[i] as number) + (baseLine[i] as number)) / 2 : null);
  const spanBLine: Series = bars.map((_, i) => midpoint(spanB, i));
  // Chikou: today's close plotted `base` bars back.
  const lagging: Series = bars.map((_, i) =>
    i + base < bars.length ? bars[i + base].close : null);

  return { conversion: conv, base: baseLine, spanA, spanB: spanBLine,
           lagging, displacement: base };
}

/** Moving-average ribbon: several EMAs at once, for fan/compression reads. */
export function maRibbon(
  bars: Bar[], periods: number[] = [8, 13, 21, 34, 55, 89],
): { period: number; values: Series }[] {
  return periods.map((period) => ({ period, values: ema(bars, period) }));
}

/**
 * Stochastic RSI: the stochastic formula applied to RSI, not to price.
 *
 * RSI has to be computed as a SERIES for this, which the scalar `rsi()`
 * above does not provide — so it is computed here rather than by calling
 * that function repeatedly over slices, which would be quadratic.
 */
export function rsiSeries(bars: Bar[], period = 14): Series {
  const out: Series = new Array(bars.length).fill(null);
  if (bars.length <= period) return out;

  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= period; i++) {
    const change = bars[i].close - bars[i - 1].close;
    if (change >= 0) gains += change;
    else losses -= change;
  }
  let averageGain = gains / period;
  let averageLoss = losses / period;
  out[period] = averageLoss === 0 ? 100
    : 100 - 100 / (1 + averageGain / averageLoss);

  for (let i = period + 1; i < bars.length; i++) {
    const change = bars[i].close - bars[i - 1].close;
    const gain = change > 0 ? change : 0;
    const loss = change < 0 ? -change : 0;
    averageGain = (averageGain * (period - 1) + gain) / period;
    averageLoss = (averageLoss * (period - 1) + loss) / period;
    out[i] = averageLoss === 0 ? 100
      : 100 - 100 / (1 + averageGain / averageLoss);
  }
  return out;
}

export function stochasticRSI(
  bars: Bar[], rsiPeriod = 14, stochPeriod = 14, smooth = 3,
): { k: Series; d: Series } {
  const values = rsiSeries(bars, rsiPeriod);
  const raw: Series = new Array(bars.length).fill(null);
  for (let i = 0; i < bars.length; i++) {
    const window = values.slice(Math.max(0, i - stochPeriod + 1), i + 1)
      .filter((v): v is number => v != null);
    if (window.length < stochPeriod) continue;
    const high = Math.max(...window);
    const low = Math.min(...window);
    const current = values[i];
    if (current == null) continue;
    raw[i] = high === low ? 50 : ((current - low) / (high - low)) * 100;
  }
  const k: Series = new Array(bars.length).fill(null);
  const d: Series = new Array(bars.length).fill(null);
  const average = (series: Series, index: number, span: number) => {
    const window = series.slice(Math.max(0, index - span + 1), index + 1)
      .filter((v): v is number => v != null);
    return window.length === span
      ? window.reduce((a, b) => a + b, 0) / span : null;
  };
  for (let i = 0; i < bars.length; i++) k[i] = average(raw, i, smooth);
  for (let i = 0; i < bars.length; i++) d[i] = average(k, i, smooth);
  return { k, d };
}

/** Chaikin Money Flow: volume weighted by where the close sat in the bar. */
export function cmf(bars: Bar[], period = 20): Series {
  const out: Series = new Array(bars.length).fill(null);
  for (let i = period - 1; i < bars.length; i++) {
    let flow = 0;
    let volume = 0;
    for (let k = i - period + 1; k <= i; k++) {
      const bar = bars[k];
      const range = bar.high - bar.low;
      const v = bar.tick_volume ?? 0;
      // A bar with no range has no meaningful position for its close, so
      // it contributes volume but no directional flow.
      const multiplier = range === 0
        ? 0 : ((bar.close - bar.low) - (bar.high - bar.close)) / range;
      flow += multiplier * v;
      volume += v;
    }
    out[i] = volume === 0 ? 0 : flow / volume;
  }
  return out;
}

/** Accumulation/Distribution: the cumulative form of the same multiplier. */
export function accumulationDistribution(bars: Bar[]): Series {
  const out: Series = new Array(bars.length).fill(null);
  let total = 0;
  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i];
    const range = bar.high - bar.low;
    const multiplier = range === 0
      ? 0 : ((bar.close - bar.low) - (bar.high - bar.close)) / range;
    total += multiplier * (bar.tick_volume ?? 0);
    out[i] = total;
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
  | "VOLUME"
  | "WMA"
  | "HMA"
  | "VWMA"
  | "DONCHIAN"
  | "KELTNER"
  | "SUPERTREND"
  | "STOCHASTIC"
  | "CCI"
  | "ROC"
  | "WILLIAMS_R"
  | "ADX"
  | "OBV"
  | "MFI"
  | "STDDEV"
  | "PSAR"
  | "ICHIMOKU"
  | "MA_RIBBON"
  | "STOCH_RSI"
  | "CMF"
  | "AD_LINE";

export interface IndicatorConfig {
  id: string;
  kind: IndicatorKind;
  period: number;
  enabled: boolean;
  colour: string;
}

/** Which indicators draw on the price chart rather than reading out below. */
export const OVERLAY_KINDS: IndicatorKind[] = [
  "SMA", "EMA", "WMA", "HMA", "VWMA", "BOLLINGER", "VWAP",
  "DONCHIAN", "KELTNER", "SUPERTREND", "PSAR", "ICHIMOKU", "MA_RIBBON",
];

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
  WMA: 20,
  HMA: 21,
  VWMA: 20,
  DONCHIAN: 20,
  KELTNER: 20,
  SUPERTREND: 10,
  STOCHASTIC: 14,
  CCI: 20,
  ROC: 12,
  WILLIAMS_R: 14,
  ADX: 14,
  OBV: 0,
  MFI: 14,
  STDDEV: 20,
  PSAR: 0,
  ICHIMOKU: 26,
  MA_RIBBON: 0,
  STOCH_RSI: 14,
  CMF: 20,
  AD_LINE: 0,
};

/** Which family each indicator belongs to, for the library UI (section 17). */
export const INDICATOR_GROUP: Record<IndicatorKind, string> = {
  SMA: "Trend", EMA: "Trend", WMA: "Trend", HMA: "Trend", VWMA: "Trend",
  BOLLINGER: "Trend", DONCHIAN: "Trend", KELTNER: "Trend",
  SUPERTREND: "Trend",
  RSI: "Momentum", MACD: "Momentum", STOCHASTIC: "Momentum",
  CCI: "Momentum", ROC: "Momentum", WILLIAMS_R: "Momentum", ADX: "Momentum",
  ATR: "Volatility", STDDEV: "Volatility",
  VOLUME: "Volume", OBV: "Volume", MFI: "Volume", VWAP: "Volume",
  PSAR: "Trend", ICHIMOKU: "Trend", MA_RIBBON: "Trend",
  STOCH_RSI: "Momentum", CMF: "Volume", AD_LINE: "Volume",
};

/** Human labels, so the picker is not a wall of abbreviations. */
export const INDICATOR_LABEL: Record<IndicatorKind, string> = {
  SMA: "Simple MA", EMA: "Exponential MA", WMA: "Weighted MA",
  HMA: "Hull MA", VWMA: "Volume-weighted MA",
  BOLLINGER: "Bollinger Bands", DONCHIAN: "Donchian Channels",
  KELTNER: "Keltner Channels", SUPERTREND: "Supertrend",
  VWAP: "VWAP (window)",
  RSI: "RSI", MACD: "MACD", STOCHASTIC: "Stochastic", CCI: "CCI",
  ROC: "Rate of Change", WILLIAMS_R: "Williams %R", ADX: "ADX / DMI",
  ATR: "ATR", STDDEV: "Standard Deviation",
  VOLUME: "Tick Volume", OBV: "On-Balance Volume", MFI: "Money Flow Index",
  PSAR: "Parabolic SAR", ICHIMOKU: "Ichimoku Cloud",
  MA_RIBBON: "Moving Average Ribbon", STOCH_RSI: "Stochastic RSI",
  CMF: "Chaikin Money Flow", AD_LINE: "Accumulation/Distribution",
};

/** Last non-null value of a series, for the readout strip. */
export function latest(series: Series): number | null {
  for (let i = series.length - 1; i >= 0; i--) {
    if (series[i] != null) return series[i] as number;
  }
  return null;
}
