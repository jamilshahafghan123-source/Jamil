import type { Timeframe, TimeframeMeta } from '@/types';

export const TIMEFRAMES: TimeframeMeta[] = [
  { id: '1m', label: '1m', seconds: 60 },
  { id: '5m', label: '5m', seconds: 300 },
  { id: '15m', label: '15m', seconds: 900 },
  { id: '30m', label: '30m', seconds: 1800 },
  { id: '1h', label: '1H', seconds: 3600 },
  { id: '4h', label: '4H', seconds: 14400 },
];

const BY_ID = new Map<Timeframe, TimeframeMeta>(TIMEFRAMES.map((t) => [t.id, t]));

export function timeframeMeta(id: Timeframe): TimeframeMeta {
  const meta = BY_ID.get(id);
  if (!meta) throw new Error(`Unknown timeframe: ${id}`);
  return meta;
}

/** How many candles each timeframe shows by default. */
export const DEFAULT_CANDLE_COUNT: Record<Timeframe, number> = {
  '1m': 320,
  '5m': 320,
  '15m': 300,
  '30m': 260,
  '1h': 240,
  '4h': 200,
};
