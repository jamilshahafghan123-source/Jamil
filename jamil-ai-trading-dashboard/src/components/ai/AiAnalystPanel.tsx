import {
  Activity,
  BrainCircuit,
  Info,
  RefreshCw,
  ShieldQuestion,
  TrendingDown,
  TrendingUp,
  Waves,
} from 'lucide-react';
import type { AiAnalysis, DataSource, MarketBias, PriceLevel } from '@/types';
import { Badge, DataSourceTag, Meter, Panel, Skeleton, Stat } from '@/components/ui';
import type { BadgeTone } from '@/components/ui';
import { cn } from '@/lib/cn';
import { formatPrice, formatRelative } from '@/lib/format';

const BIAS_TONE: Record<MarketBias, BadgeTone> = {
  bullish: 'bull',
  bearish: 'bear',
  neutral: 'muted',
};

const BIAS_TEXT: Record<MarketBias, string> = {
  bullish: 'text-bull-400',
  bearish: 'text-bear-400',
  neutral: 'text-ink-200',
};

const BIAS_RING: Record<MarketBias, string> = {
  bullish: 'from-bull-500/15 ring-bull-500/25',
  bearish: 'from-bear-500/15 ring-bear-500/25',
  neutral: 'from-base-750 ring-base-600',
};

function LevelRow({ level, tone }: { level: PriceLevel; tone: 'bull' | 'bear' }) {
  return (
    <li className="flex items-center gap-3">
      <span
        className={cn(
          'num w-7 shrink-0 rounded text-center text-[10px] font-bold',
          tone === 'bull' ? 'text-bull-400' : 'text-bear-400',
        )}
      >
        {level.label}
      </span>
      <span className="num flex-1 text-sm font-semibold text-ink-100">
        {formatPrice(level.price)}
      </span>
      <span className="w-20 shrink-0">
        <Meter value={level.strength * 100} tone={tone} />
      </span>
    </li>
  );
}

function LoadingState() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-24 w-full" />
      <div className="grid gap-3 sm:grid-cols-2">
        <Skeleton className="h-20" />
        <Skeleton className="h-20" />
      </div>
      <Skeleton className="h-28 w-full" />
    </div>
  );
}

export function AiAnalystPanel({
  analysis,
  loading,
  source,
  onRefresh,
  currentPrice,
}: {
  analysis: AiAnalysis | null;
  loading: boolean;
  source: DataSource;
  onRefresh: () => void;
  currentPrice: number | null;
}) {
  const BiasIcon =
    analysis?.bias === 'bullish' ? TrendingUp : analysis?.bias === 'bearish' ? TrendingDown : Waves;

  return (
    <Panel
      icon={<BrainCircuit className="h-4.5 w-4.5" />}
      title="AI Analyst"
      subtitle={
        analysis
          ? `${analysis.symbol} · ${analysis.timeframe} · model ${analysis.modelName}`
          : 'Waiting for analysis'
      }
      actions={
        <>
          <Badge tone="info" icon={<ShieldQuestion className="h-3 w-3" />}>
            AI analysis
          </Badge>
          <DataSourceTag source={source} />
          <button
            type="button"
            onClick={onRefresh}
            aria-label="Re-run analysis"
            title="Re-run analysis"
            className="grid h-7 w-7 place-items-center rounded-md border border-base-700 bg-base-900/70 text-ink-400 hover:text-gold-300"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </button>
        </>
      }
      footer={
        analysis ? (
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Info className="h-3.5 w-3.5 shrink-0 text-ink-500" />
            <span className="flex-1 min-w-[16rem]">
              AI-generated analysis of historical price structure. Not a prediction, not a guarantee,
              and not investment advice.
            </span>
            <span className="text-ink-500">Generated {formatRelative(analysis.generatedAt)}</span>
          </span>
        ) : null
      }
    >
      {!analysis ? (
        <LoadingState />
      ) : (
        <div className="space-y-5">
          {/* Bias + confidence ------------------------------------------ */}
          <div
            className={cn(
              'rounded-xl bg-gradient-to-br to-transparent p-4 ring-1 ring-inset',
              BIAS_RING[analysis.bias],
            )}
          >
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    'grid h-11 w-11 place-items-center rounded-xl bg-base-900/70',
                    BIAS_TEXT[analysis.bias],
                  )}
                >
                  <BiasIcon className="h-6 w-6" />
                </span>
                <div>
                  <div className="text-[11px] font-medium tracking-wider text-ink-400 uppercase">
                    Market bias
                  </div>
                  <div
                    className={cn(
                      'text-2xl font-bold capitalize',
                      BIAS_TEXT[analysis.bias],
                    )}
                  >
                    {analysis.bias}
                  </div>
                </div>
              </div>

              <div className="min-w-[11rem] flex-1 sm:max-w-xs">
                <div className="flex items-baseline justify-between">
                  <span className="text-[11px] font-medium tracking-wider text-ink-400 uppercase">
                    Confidence
                  </span>
                  <span className="num text-xl font-bold text-gold-300">{analysis.confidence}%</span>
                </div>
                <Meter value={analysis.confidence} tone="gold" className="mt-2" />
                <p className="mt-1.5 text-[11px] text-ink-500">
                  Model self-scored certainty — higher is not a promise of accuracy.
                </p>
              </div>
            </div>
          </div>

          {/* Trend + momentum ------------------------------------------- */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-base-700 bg-base-900/50 p-3.5">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-[11px] font-medium tracking-wider text-ink-400 uppercase">
                  <Activity className="h-3.5 w-3.5" /> Trend
                </span>
                <Badge tone={BIAS_TONE[analysis.trend.direction]}>{analysis.trend.strength}</Badge>
              </div>
              <div className={cn('mt-2 text-lg font-semibold capitalize', BIAS_TEXT[analysis.trend.direction])}>
                {analysis.trend.direction}
              </div>
              <p className="mt-1 text-xs leading-relaxed text-ink-400">{analysis.trend.description}</p>
            </div>

            <div className="rounded-lg border border-base-700 bg-base-900/50 p-3.5">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-[11px] font-medium tracking-wider text-ink-400 uppercase">
                  <Waves className="h-3.5 w-3.5" /> Momentum
                </span>
                <Badge
                  tone={
                    analysis.momentum.state === 'accelerating'
                      ? 'bull'
                      : analysis.momentum.state === 'reversing'
                        ? 'bear'
                        : 'muted'
                  }
                >
                  RSI {analysis.momentum.rsi}
                </Badge>
              </div>
              <div className="mt-2 text-lg font-semibold text-ink-100 capitalize">
                {analysis.momentum.state}
              </div>
              <p className="mt-1 text-xs leading-relaxed text-ink-400">
                {analysis.momentum.description}
              </p>
            </div>
          </div>

          {/* Levels ------------------------------------------------------ */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-base-700 bg-base-900/50 p-3.5">
              <div className="text-[11px] font-medium tracking-wider text-bull-400 uppercase">
                Support
              </div>
              <ul className="mt-2.5 space-y-2">
                {analysis.support.map((level) => (
                  <LevelRow key={level.label} level={level} tone="bull" />
                ))}
              </ul>
            </div>
            <div className="rounded-lg border border-base-700 bg-base-900/50 p-3.5">
              <div className="text-[11px] font-medium tracking-wider text-bear-400 uppercase">
                Resistance
              </div>
              <ul className="mt-2.5 space-y-2">
                {analysis.resistance.map((level) => (
                  <LevelRow key={level.label} level={level} tone="bear" />
                ))}
              </ul>
            </div>
          </div>

          {/* Scenario ---------------------------------------------------- */}
          <div className="rounded-lg border border-gold-400/20 bg-gold-400/5 p-3.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium tracking-wider text-gold-300 uppercase">
                Illustrative scenario
              </span>
              <Badge tone="gold">Not an order</Badge>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat
                label="Entry zone"
                value={`${formatPrice(analysis.entryZone.from)} – ${formatPrice(analysis.entryZone.to)}`}
                tone="gold"
                size="sm"
                hint={currentPrice ? `Now ${formatPrice(currentPrice)}` : undefined}
              />
              <Stat
                label="Stop loss"
                value={formatPrice(analysis.stopLoss)}
                tone="bear"
                size="sm"
                hint="Invalidation level"
              />
              <Stat
                label="Take profit"
                value={analysis.takeProfit.map((tp) => formatPrice(tp)).join(' · ')}
                tone="bull"
                size="sm"
                hint={`${analysis.takeProfit.length} staged targets`}
              />
              <Stat
                label="Risk / reward"
                value={`1 : ${analysis.riskReward.toFixed(2)}`}
                size="sm"
                hint="At the second target"
              />
            </div>
          </div>

          {/* Factors ----------------------------------------------------- */}
          <div className="grid grid-cols-2 gap-2">
            {analysis.factors.map((factor) => (
              <div
                key={factor.label}
                className="rounded-lg border border-base-700 bg-base-900/50 px-3 py-2"
              >
                <div className="truncate text-[10px] font-medium tracking-wider text-ink-400 uppercase">
                  {factor.label}
                </div>
                <div className={cn('num mt-1 truncate text-sm font-semibold', BIAS_TEXT[factor.sentiment])}>
                  {factor.value}
                </div>
              </div>
            ))}
          </div>

          {/* Explanation -------------------------------------------------- */}
          <div className="rounded-lg border border-base-700 bg-base-900/50 p-3.5">
            <div className="text-[11px] font-medium tracking-wider text-ink-400 uppercase">
              AI explanation
            </div>
            <p className="mt-2 text-sm leading-relaxed text-ink-200">{analysis.explanation}</p>
          </div>
        </div>
      )}
    </Panel>
  );
}
