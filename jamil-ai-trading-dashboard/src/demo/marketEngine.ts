/**
 * Synthetic GOLD (XAUUSD) market generator.
 *
 * This is DEMO data. It exists so the dashboard can be built, reviewed and
 * demonstrated before the Backend API / MT5 Bridge is available. Nothing here
 * is a market feed and nothing here should ever be presented as one.
 *
 * The engine keeps a one-minute base series as the single source of truth and
 * aggregates it into the higher timeframes, so every chart agrees on price.
 */
import type { Candle, MarketSession, Quote, Timeframe } from '@/types';
import { gaussian, mulberry32 } from './random';
import { timeframeMeta } from './timeframes';

const SYMBOL = 'XAUUSD';
const DESCRIPTION = 'Gold vs US Dollar';
const DIGITS = 2;
/** Anchor price for the synthetic series. */
const BASE_PRICE = 3418.6;
/** Minutes of one-minute history to generate (~42 days, enough for 200 4H bars). */
const HISTORY_MINUTES = 60_480;
const SEED = 20260818;

/** Volatility multiplier by UTC hour — quiet Asia, busy London/NY overlap. */
const SESSION_VOLATILITY = [
  0.55, 0.5, 0.5, 0.55, 0.6, 0.7, 0.85, 1.0, 1.25, 1.35, 1.2, 1.05, 1.15, 1.55, 1.7, 1.6, 1.35,
  1.1, 0.9, 0.8, 0.75, 0.7, 0.65, 0.6,
];

function floorToBucket(epochSeconds: number, bucketSeconds: number): number {
  return Math.floor(epochSeconds / bucketSeconds) * bucketSeconds;
}

/**
 * The synthetic market is open 24/5, closing Friday 21:00 UTC and reopening
 * Sunday 21:00 UTC — the same rhythm as a real spot-gold CFD.
 */
export function marketSessionAt(date: Date): MarketSession {
  const day = date.getUTCDay();
  const hour = date.getUTCHours();
  if (day === 6) return 'closed';
  if (day === 0) return hour >= 21 ? 'pre-market' : 'closed';
  if (day === 5 && hour >= 21) return 'closed';
  // Daily broker maintenance break.
  if (hour === 21) return 'after-hours';
  return 'open';
}

class DemoMarketEngine {
  private readonly rand = mulberry32(SEED);
  private minutes: Candle[] = [];
  private readonly aggregates = new Map<Timeframe, Candle[]>();
  private price = BASE_PRICE;
  private spread = 0.28;
  private dayOpen = BASE_PRICE;
  private previousClose = BASE_PRICE;
  private trend = 0;
  private lastTickAt = Date.now();

  constructor() {
    this.generateHistory();
  }

  private generateHistory(): void {
    const nowMinute = floorToBucket(Math.floor(Date.now() / 1000), 60);
    const start = nowMinute - (HISTORY_MINUTES - 1) * 60;

    // Walk backwards from the anchor so the newest price lands near BASE_PRICE.
    const closes: number[] = new Array(HISTORY_MINUTES);
    let value = BASE_PRICE;
    let drift = 0;
    for (let i = HISTORY_MINUTES - 1; i >= 0; i -= 1) {
      closes[i] = value;
      const hour = new Date((start + i * 60) * 1000).getUTCHours();
      const vol = 0.34 * SESSION_VOLATILITY[hour];
      // Slowly mean-reverting drift produces multi-day swings instead of noise.
      drift = drift * 0.9995 + gaussian(this.rand) * 0.0016;
      drift = Math.max(-0.05, Math.min(0.05, drift));
      const shock = this.rand() < 0.0006 ? gaussian(this.rand) * vol * 9 : 0;
      value -= gaussian(this.rand) * vol + drift + shock;
      // Keep the series in a believable band around the anchor.
      value += (BASE_PRICE - value) * 0.00004;
    }

    const bars: Candle[] = new Array(HISTORY_MINUTES);
    for (let i = 0; i < HISTORY_MINUTES; i += 1) {
      const time = start + i * 60;
      const open = i === 0 ? closes[0] : closes[i - 1];
      const close = closes[i];
      const hour = new Date(time * 1000).getUTCHours();
      const wick = 0.22 * SESSION_VOLATILITY[hour] * (0.4 + this.rand());
      const high = Math.max(open, close) + wick * this.rand();
      const low = Math.min(open, close) - wick * this.rand();
      const range = Math.max(high - low, 0.01);
      const volume = Math.round(
        (180 + range * 900) * SESSION_VOLATILITY[hour] * (0.6 + this.rand() * 0.9),
      );
      bars[i] = { time, open, high, low, close, volume };
    }

    this.minutes = bars;
    this.price = bars[bars.length - 1].close;
    this.previousClose = this.closeOfPreviousDay();
    this.dayOpen = this.openOfCurrentDay();
  }

  private openOfCurrentDay(): number {
    const startOfDay = Math.floor(Date.now() / 86_400_000) * 86_400;
    const bar = this.minutes.find((b) => b.time >= startOfDay);
    return bar ? bar.open : this.minutes[0].open;
  }

  private closeOfPreviousDay(): number {
    const startOfDay = Math.floor(Date.now() / 86_400_000) * 86_400;
    for (let i = this.minutes.length - 1; i >= 0; i -= 1) {
      if (this.minutes[i].time < startOfDay) return this.minutes[i].close;
    }
    return this.minutes[0].close;
  }

  /** Advances the synthetic price by one tick and folds it into every series. */
  tick(): void {
    const now = Date.now();
    const elapsed = Math.min(5, (now - this.lastTickAt) / 1000);
    this.lastTickAt = now;

    const hour = new Date(now).getUTCHours();
    const session = marketSessionAt(new Date(now));
    const sessionScale = session === 'open' ? 1 : session === 'after-hours' ? 0.35 : 0.08;
    const vol = 0.34 * SESSION_VOLATILITY[hour] * sessionScale;

    this.trend = this.trend * 0.985 + gaussian(this.rand) * 0.008;
    this.price += (gaussian(this.rand) * vol + this.trend) * Math.sqrt(Math.max(elapsed, 0.2) / 60);
    this.spread = Math.max(0.14, Math.min(0.9, this.spread + gaussian(this.rand) * 0.02));

    const minute = floorToBucket(Math.floor(now / 1000), 60);
    const last = this.minutes[this.minutes.length - 1];
    if (minute > last.time) {
      this.minutes.push({
        time: minute,
        open: last.close,
        high: Math.max(last.close, this.price),
        low: Math.min(last.close, this.price),
        close: this.price,
        volume: Math.round(40 + this.rand() * 120),
      });
      if (this.minutes.length > HISTORY_MINUTES + 600) this.minutes.shift();
    } else {
      last.close = this.price;
      last.high = Math.max(last.high, this.price);
      last.low = Math.min(last.low, this.price);
      last.volume += Math.round(4 + this.rand() * 26);
    }

    for (const [timeframe, series] of this.aggregates) {
      this.foldIntoAggregate(timeframe, series);
    }
  }

  private foldIntoAggregate(timeframe: Timeframe, series: Candle[]): void {
    const { seconds } = timeframeMeta(timeframe);
    const bucket = floorToBucket(Math.floor(Date.now() / 1000), seconds);
    const last = series[series.length - 1];
    if (!last) return;
    if (bucket > last.time) {
      series.push({
        time: bucket,
        open: last.close,
        high: Math.max(last.close, this.price),
        low: Math.min(last.close, this.price),
        close: this.price,
        volume: Math.round(60 + this.rand() * 200),
      });
      if (series.length > 1200) series.shift();
    } else {
      last.close = this.price;
      last.high = Math.max(last.high, this.price);
      last.low = Math.min(last.low, this.price);
      last.volume += Math.round(4 + this.rand() * 26);
    }
  }

  private aggregate(timeframe: Timeframe): Candle[] {
    const cached = this.aggregates.get(timeframe);
    if (cached) return cached;

    const { seconds } = timeframeMeta(timeframe);
    if (seconds === 60) {
      const copy = this.minutes.map((b) => ({ ...b }));
      this.aggregates.set(timeframe, copy);
      return copy;
    }

    const out: Candle[] = [];
    let current: Candle | null = null;
    for (const bar of this.minutes) {
      const bucket = floorToBucket(bar.time, seconds);
      if (!current || current.time !== bucket) {
        if (current) out.push(current);
        current = { ...bar, time: bucket };
      } else {
        current.high = Math.max(current.high, bar.high);
        current.low = Math.min(current.low, bar.low);
        current.close = bar.close;
        current.volume += bar.volume;
      }
    }
    if (current) out.push(current);
    this.aggregates.set(timeframe, out);
    return out;
  }

  getCandles(timeframe: Timeframe, count: number): Candle[] {
    const series = this.aggregate(timeframe);
    return series.slice(-count).map((b) => ({ ...b }));
  }

  getQuote(): Quote {
    const half = this.spread / 2;
    const bid = this.price - half;
    const ask = this.price + half;
    const now = new Date();
    const dayChange = this.price - this.dayOpen;
    const todayBars = this.minutes.filter(
      (b) => b.time >= Math.floor(Date.now() / 86_400_000) * 86_400,
    );
    const dayHigh = todayBars.length
      ? Math.max(...todayBars.map((b) => b.high))
      : Math.max(this.price, this.dayOpen);
    const dayLow = todayBars.length
      ? Math.min(...todayBars.map((b) => b.low))
      : Math.min(this.price, this.dayOpen);

    return {
      symbol: SYMBOL,
      description: DESCRIPTION,
      bid: round(bid),
      ask: round(ask),
      price: round(this.price),
      spreadPoints: Math.round(this.spread * 100),
      dayChange: round(dayChange),
      dayChangePercent: (dayChange / this.dayOpen) * 100,
      dayHigh: round(dayHigh),
      dayLow: round(dayLow),
      dayOpen: round(this.dayOpen),
      previousClose: round(this.previousClose),
      session: marketSessionAt(now),
      digits: DIGITS,
      updatedAt: now.toISOString(),
    };
  }

  get currentPrice(): number {
    return round(this.price);
  }
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

export const demoMarket = new DemoMarketEngine();
export const DEMO_SYMBOL = SYMBOL;
