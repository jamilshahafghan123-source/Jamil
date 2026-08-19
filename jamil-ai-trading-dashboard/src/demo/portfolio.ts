/**
 * DEMO account, positions and trade history.
 *
 * Values are derived from the synthetic price so floating P/L moves with the
 * chart. No order is ever sent anywhere — this is presentation state only.
 */
import type {
  AccountSnapshot,
  HistoryTrade,
  Position,
  RiskSettings,
  RiskUsage,
} from '@/types';
import { demoMarket } from './marketEngine';
import { mulberry32 } from './random';

/** Ounces per 1.00 lot. XAUUSD is 100, XAGUSD is 5000. */
const CONTRACT_SIZE: Record<string, number> = {
  XAUUSD: 100,
  XAGUSD: 5000,
};

const STARTING_BALANCE = 50_000;
const LEVERAGE = 100;

interface PositionSeed {
  id: string;
  symbol: string;
  direction: 'buy' | 'sell';
  volume: number;
  /** Offset from the live gold price at seed time, in USD. */
  entryOffset: number;
  stopOffset: number | null;
  takeProfitOffset: number | null;
  openedMinutesAgo: number;
  swap: number;
  commission: number;
  /** Fixed price for symbols the demo engine does not simulate. */
  staticPrice?: number;
}

const POSITION_SEEDS: PositionSeed[] = [
  {
    id: 'D-100241',
    symbol: 'XAUUSD',
    direction: 'buy',
    volume: 0.4,
    entryOffset: -6.35,
    stopOffset: -14.8,
    takeProfitOffset: 18.4,
    openedMinutesAgo: 214,
    swap: -1.82,
    commission: -3.2,
  },
  {
    id: 'D-100238',
    symbol: 'XAUUSD',
    direction: 'buy',
    volume: 0.15,
    entryOffset: -2.1,
    stopOffset: -9.4,
    takeProfitOffset: 11.9,
    openedMinutesAgo: 96,
    swap: -0.44,
    commission: -1.2,
  },
  {
    id: 'D-100235',
    symbol: 'XAUUSD',
    direction: 'sell',
    volume: 0.1,
    entryOffset: 3.8,
    stopOffset: 10.6,
    takeProfitOffset: -12.2,
    openedMinutesAgo: 41,
    swap: 0.12,
    commission: -0.8,
  },
  {
    id: 'D-100230',
    symbol: 'XAGUSD',
    direction: 'buy',
    volume: 0.2,
    entryOffset: 0,
    stopOffset: null,
    takeProfitOffset: null,
    openedMinutesAgo: 620,
    swap: -0.35,
    commission: -0.9,
    staticPrice: 38.42,
  },
];

/** Anchor so entry prices stay fixed while the live price moves around them. */
const ANCHOR_PRICE = demoMarket.currentPrice;

export function buildDemoPositions(): Position[] {
  const gold = demoMarket.currentPrice;
  const now = Date.now();

  return POSITION_SEEDS.map((seed) => {
    const contract = CONTRACT_SIZE[seed.symbol] ?? 100;
    const entryPrice = round(
      seed.staticPrice !== undefined
        ? seed.staticPrice - 0.31
        : ANCHOR_PRICE + seed.entryOffset,
    );
    const currentPrice = round(seed.staticPrice ?? gold);
    const sign = seed.direction === 'buy' ? 1 : -1;
    const gross = (currentPrice - entryPrice) * sign * contract * seed.volume;
    const pnl = round(gross + seed.swap + seed.commission);
    const notional = entryPrice * contract * seed.volume;

    return {
      id: seed.id,
      symbol: seed.symbol,
      direction: seed.direction,
      volume: seed.volume,
      entryPrice,
      currentPrice,
      stopLoss: seed.stopOffset === null ? null : round(entryPrice + seed.stopOffset),
      takeProfit: seed.takeProfitOffset === null ? null : round(entryPrice + seed.takeProfitOffset),
      pnl,
      pnlPercent: round((pnl / (notional / LEVERAGE)) * 100),
      swap: seed.swap,
      commission: seed.commission,
      status: 'open' as const,
      openedAt: new Date(now - seed.openedMinutesAgo * 60_000).toISOString(),
    };
  });
}

export function buildDemoAccount(positions: Position[]): AccountSnapshot {
  const floating = positions.reduce((sum, p) => sum + p.pnl, 0);
  const margin = positions.reduce((sum, p) => {
    const contract = CONTRACT_SIZE[p.symbol] ?? 100;
    return sum + (p.entryPrice * contract * p.volume) / LEVERAGE;
  }, 0);
  const realisedToday = 184.6;
  const balance = STARTING_BALANCE + realisedToday;
  const equity = balance + floating;
  const todayPnl = realisedToday + floating;

  return {
    accountType: 'demo',
    broker: 'Demo Broker (MT5 sandbox)',
    login: '5100 4482',
    currency: 'USD',
    leverage: LEVERAGE,
    balance: round(balance),
    equity: round(equity),
    margin: round(margin),
    freeMargin: round(equity - margin),
    marginLevel: margin > 0 ? round((equity / margin) * 100) : null,
    todayPnl: round(todayPnl),
    todayPnlPercent: round((todayPnl / STARTING_BALANCE) * 100),
    openPositions: positions.length,
    updatedAt: new Date().toISOString(),
  };
}

export const DEMO_RISK_SETTINGS: RiskSettings = {
  riskPerTradePercent: 0.5,
  maxDailyLossPercent: 2,
  maxOpenPositions: 5,
  requireStopLoss: true,
  // Hard-locked for the whole demo phase. Do not flip this without an
  // explicit, reviewed configuration change on the backend as well.
  liveTradingEnabled: false,
  demoTradingEnabled: false,
  maxLotSize: 1,
};

export function buildDemoRiskUsage(
  account: AccountSnapshot,
  positions: Position[],
  settings: RiskSettings,
): RiskUsage {
  const limit = round((STARTING_BALANCE * settings.maxDailyLossPercent) / 100);
  return {
    dailyLossUsed: account.todayPnl < 0 ? round(Math.abs(account.todayPnl)) : 0,
    dailyLossLimit: limit,
    openPositions: positions.length,
    positionsWithoutStop: positions.filter((p) => p.stopLoss === null).length,
    updatedAt: new Date().toISOString(),
  };
}

const HISTORY_SEED = 74213;

export function buildDemoHistory(): HistoryTrade[] {
  const rand = mulberry32(HISTORY_SEED);
  const trades: HistoryTrade[] = [];
  const now = Date.now();
  let price = ANCHOR_PRICE;

  for (let i = 0; i < 24; i += 1) {
    const direction = rand() > 0.45 ? 'buy' : 'sell';
    const sign = direction === 'buy' ? 1 : -1;
    const volume = round2(0.05 + Math.floor(rand() * 8) * 0.05);
    const entryPrice = round(price + (rand() - 0.5) * 24);
    const risk = 6 + rand() * 9;
    const win = rand() < 0.58;
    const rMultiple = win ? 1.2 + rand() * 2.1 : -1;
    const exitPrice = round(entryPrice + sign * risk * rMultiple);
    const pnl = round((exitPrice - entryPrice) * sign * 100 * volume);
    const openedAt = now - (i + 1) * (5.5 * 3_600_000) - rand() * 3_600_000;
    const closedAt = openedAt + (25 + rand() * 260) * 60_000;

    trades.push({
      id: `D-${100_229 - i}`,
      symbol: 'XAUUSD',
      direction,
      volume,
      entryPrice,
      exitPrice,
      stopLoss: round(entryPrice - sign * risk),
      takeProfit: round(entryPrice + sign * risk * 2.4),
      pnl,
      pnlPercent: round((pnl / (entryPrice * 100 * volume / LEVERAGE)) * 100),
      closeReason: win ? (rand() > 0.25 ? 'take-profit' : 'manual') : rand() > 0.2 ? 'stop-loss' : 'manual',
      openedAt: new Date(openedAt).toISOString(),
      closedAt: new Date(closedAt).toISOString(),
    });

    price += (rand() - 0.5) * 12;
  }

  return trades;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}
