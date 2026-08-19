/**
 * DEMO AI analysis.
 *
 * Produces a structured, plausible read of the synthetic series using ordinary
 * technical indicators. It stands in for the Backend AI service so the panel
 * can be designed and reviewed. It is NOT a model, NOT a prediction, and the
 * UI labels it as such wherever it appears.
 */
import type { AiAnalysis, Candle, MarketBias, MomentumState, Timeframe, TrendStrength } from '@/types';
import { atr, ema, lastFinite, rsi, swingLevels } from '@/lib/indicators';
import { clamp } from '@/lib/format';
import { DEMO_SYMBOL } from './marketEngine';

const BIAS_WORD: Record<MarketBias, string> = {
  bullish: 'buyers',
  bearish: 'sellers',
  neutral: 'neither side',
};

export function buildDemoAnalysis(candles: Candle[], timeframe: Timeframe): AiAnalysis {
  const closes = candles.map((c) => c.close);
  const price = closes[closes.length - 1] ?? 0;

  const emaFast = lastFinite(ema(closes, 21));
  const emaSlow = lastFinite(ema(closes, 55));
  const emaTrend = lastFinite(ema(closes, 120));
  const rsiSeries = rsi(closes, 14);
  const rsiNow = lastFinite(rsiSeries);
  const rsiPrev = Number.isFinite(rsiSeries[rsiSeries.length - 6])
    ? rsiSeries[rsiSeries.length - 6]
    : rsiNow;
  const range = atr(candles, 14) || price * 0.001;

  const separation = (emaFast - emaSlow) / (range || 1);
  const slope = (price - (closes[closes.length - 20] ?? price)) / (range || 1);

  const bias: MarketBias =
    separation > 0.35 && slope > 0.2 ? 'bullish' : separation < -0.35 && slope < -0.2 ? 'bearish' : 'neutral';

  const strength: TrendStrength =
    Math.abs(separation) > 1.4 ? 'strong' : Math.abs(separation) > 0.6 ? 'moderate' : Math.abs(separation) > 0.25 ? 'weak' : 'flat';

  const rsiDelta = rsiNow - rsiPrev;
  const momentumState: MomentumState =
    Math.sign(rsiDelta) !== 0 && Math.sign(rsiDelta) !== (bias === 'bearish' ? -1 : 1) && Math.abs(rsiDelta) > 6
      ? 'reversing'
      : Math.abs(rsiDelta) > 7
        ? 'accelerating'
        : Math.abs(rsiDelta) > 2.5
          ? 'steady'
          : 'fading';

  const supports = swingLevels(candles, 'low')
    .filter((l) => l.price < price)
    .slice(0, 3)
    .map((l, i) => ({
      label: `S${i + 1}`,
      price: round(l.price),
      strength: clamp(l.touches / 4, 0.2, 1),
    }));
  const resistances = swingLevels(candles, 'high')
    .filter((l) => l.price > price)
    .slice(0, 3)
    .map((l, i) => ({
      label: `R${i + 1}`,
      price: round(l.price),
      strength: clamp(l.touches / 4, 0.2, 1),
    }));

  const nearestSupport = supports[0]?.price ?? round(price - range * 2.5);
  const nearestResistance = resistances[0]?.price ?? round(price + range * 2.5);

  const direction = bias === 'bearish' ? -1 : 1;
  const entryFrom = round(price - range * 0.35 * direction);
  const entryTo = round(price + range * 0.15 * direction);
  const entryMid = (entryFrom + entryTo) / 2;
  const stopLoss =
    bias === 'bearish'
      ? round(Math.max(nearestResistance + range * 0.4, entryMid + range * 1.4))
      : round(Math.min(nearestSupport - range * 0.4, entryMid - range * 1.4));
  const riskDistance = Math.abs(entryMid - stopLoss) || range;
  const takeProfit = [1.5, 2.5, 3.5].map((r) => round(entryMid + riskDistance * r * direction));
  const riskReward = round(Math.abs(takeProfit[1] - entryMid) / riskDistance);

  // Confidence blends trend separation, momentum agreement and RSI extremity.
  const agreement = bias === 'neutral' ? 0 : Math.sign(rsiNow - 50) === direction ? 1 : -0.6;
  const rawConfidence =
    46 +
    Math.min(22, Math.abs(separation) * 12) +
    agreement * 11 +
    (strength === 'strong' ? 8 : strength === 'moderate' ? 4 : 0) +
    (momentumState === 'accelerating' ? 5 : momentumState === 'reversing' ? -9 : 0) +
    (price > emaTrend === (direction > 0) ? 5 : -5);
  const confidence = Math.round(clamp(rawConfidence, 18, 88));

  return {
    symbol: DEMO_SYMBOL,
    timeframe,
    bias,
    confidence,
    trend: {
      direction: bias,
      strength,
      description:
        bias === 'neutral'
          ? `Price is oscillating around the ${timeframe} moving averages with no clear control by ${BIAS_WORD.neutral}.`
          : `The ${timeframe} 21 EMA sits ${bias === 'bullish' ? 'above' : 'below'} the 55 EMA by ${Math.abs(
              emaFast - emaSlow,
            ).toFixed(2)} USD, and ${BIAS_WORD[bias]} are holding structure.`,
    },
    momentum: {
      state: momentumState,
      rsi: Math.round(rsiNow * 10) / 10,
      description: `RSI(14) at ${rsiNow.toFixed(1)}, ${
        rsiDelta >= 0 ? 'up' : 'down'
      } ${Math.abs(rsiDelta).toFixed(1)} points over the last 5 candles.`,
    },
    support: supports.length ? supports : [{ label: 'S1', price: round(price - range * 2), strength: 0.4 }],
    resistance: resistances.length
      ? resistances
      : [{ label: 'R1', price: round(price + range * 2), strength: 0.4 }],
    entryZone: { from: Math.min(entryFrom, entryTo), to: Math.max(entryFrom, entryTo) },
    stopLoss,
    takeProfit,
    riskReward,
    explanation: buildExplanation({
      bias,
      confidence,
      timeframe,
      price,
      rsiNow,
      strength,
      momentumState,
      nearestSupport,
      nearestResistance,
      range,
    }),
    factors: [
      {
        label: 'EMA structure',
        value: `21 ${emaFast >= emaSlow ? '>' : '<'} 55 ${emaSlow >= emaTrend ? '>' : '<'} 120`,
        sentiment: emaFast >= emaSlow ? 'bullish' : 'bearish',
      },
      {
        label: 'RSI (14)',
        value: rsiNow.toFixed(1),
        sentiment: rsiNow > 55 ? 'bullish' : rsiNow < 45 ? 'bearish' : 'neutral',
      },
      {
        label: 'ATR (14)',
        value: `${range.toFixed(2)} USD`,
        sentiment: 'neutral',
      },
      {
        label: 'Structure vs 120 EMA',
        value: price >= emaTrend ? 'Above' : 'Below',
        sentiment: price >= emaTrend ? 'bullish' : 'bearish',
      },
    ],
    generatedAt: new Date().toISOString(),
    modelName: 'demo-analyst-rules-v1',
  };
}

function buildExplanation(input: {
  bias: MarketBias;
  confidence: number;
  timeframe: Timeframe;
  price: number;
  rsiNow: number;
  strength: TrendStrength;
  momentumState: MomentumState;
  nearestSupport: number;
  nearestResistance: number;
  range: number;
}): string {
  const {
    bias,
    confidence,
    timeframe,
    price,
    rsiNow,
    strength,
    momentumState,
    nearestSupport,
    nearestResistance,
    range,
  } = input;

  const headline =
    bias === 'bullish'
      ? `Gold is holding a ${strength} upward structure on the ${timeframe} chart.`
      : bias === 'bearish'
        ? `Gold is under ${strength} downward pressure on the ${timeframe} chart.`
        : `Gold is ranging on the ${timeframe} chart with no committed direction.`;

  const context = `Price is trading at ${price.toFixed(2)} between support at ${nearestSupport.toFixed(
    2,
  )} and resistance at ${nearestResistance.toFixed(2)}, an area roughly ${(
    (nearestResistance - nearestSupport) / range
  ).toFixed(1)} ATR wide.`;

  const momentum = `Momentum is ${momentumState} with RSI at ${rsiNow.toFixed(
    1,
  )}, which ${momentumState === 'reversing' ? 'argues against chasing the current move' : 'is consistent with the read above'}.`;

  const plan =
    bias === 'neutral'
      ? 'The scenario below is a range-fade idea only; without a break of either boundary there is no high-quality setup.'
      : `The scenario below is a ${bias === 'bullish' ? 'long' : 'short'} continuation idea, invalidated if price closes beyond the stop level.`;

  return `${headline} ${context} ${momentum} ${plan} Confidence is ${confidence}% — this is a probabilistic read of historical price structure, not a forecast, and it does not account for news, liquidity or slippage.`;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
