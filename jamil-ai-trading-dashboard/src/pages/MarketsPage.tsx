import { useDashboard } from '@/context/dashboardContext';
import { PageHeading } from '@/components/layout/PageHeading';
import { GoldMarketCard } from '@/components/market/GoldMarketCard';
import { ChartPanel } from '@/components/chart/ChartPanel';
import { Badge, DataSourceTag, Panel } from '@/components/ui';
import { formatPrice } from '@/lib/format';
import { TIMEFRAMES } from '@/demo/timeframes';

/** Watchlist stub — extra symbols arrive from GET /api/v1/market/symbols. */
const WATCHLIST = [
  { symbol: 'XAUUSD', name: 'Gold vs US Dollar', tracked: true },
  { symbol: 'XAGUSD', name: 'Silver vs US Dollar', tracked: false },
  { symbol: 'EURUSD', name: 'Euro vs US Dollar', tracked: false },
  { symbol: 'USDJPY', name: 'US Dollar vs Yen', tracked: false },
];

export function MarketsPage() {
  const { source, quote, candles, candlesLoading, timeframe, setTimeframe, analysis, lastMarketDataAt } =
    useDashboard();

  const activeMeta = TIMEFRAMES.find((t) => t.id === timeframe);

  return (
    <>
      <PageHeading
        title="Markets"
        description="GOLD is the only instrument wired up in this build. Additional symbols will be listed once the backend exposes them."
        actions={<DataSourceTag source={source} />}
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-8">
          <GoldMarketCard quote={quote} source={source} lastUpdatedAt={lastMarketDataAt} />
        </div>

        <div className="xl:col-span-4">
          <Panel title="Watchlist" subtitle="Symbols the dashboard can display" bodyClassName="p-0 sm:p-0">
            <ul>
              {WATCHLIST.map((item) => (
                <li
                  key={item.symbol}
                  className="flex items-center justify-between gap-3 border-b border-base-800/80 px-4 py-3 last:border-0"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-ink-100">{item.symbol}</div>
                    <div className="truncate text-[11px] text-ink-400">{item.name}</div>
                  </div>
                  {item.tracked ? (
                    <span className="num text-sm font-semibold text-gold-300">
                      {quote ? formatPrice(quote.price) : '—'}
                    </span>
                  ) : (
                    <Badge tone="muted">Not connected</Badge>
                  )}
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        <div className="min-w-0 xl:col-span-12">
          <ChartPanel
            candles={candles}
            loading={candlesLoading}
            timeframe={timeframe}
            onTimeframeChange={setTimeframe}
            analysis={analysis}
            source={source}
            height={560}
          />
        </div>

        <div className="xl:col-span-12">
          <Panel title="Timeframes" subtitle="Aggregation used for the chart and the AI analysis">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf.id}
                  type="button"
                  onClick={() => setTimeframe(tf.id)}
                  className={`rounded-lg border px-3 py-2.5 text-left transition-colors ${
                    tf.id === timeframe
                      ? 'border-gold-400/30 bg-gold-400/10'
                      : 'border-base-700 bg-base-900/50 hover:border-base-600'
                  }`}
                >
                  <div className="text-sm font-semibold text-ink-100">{tf.label}</div>
                  <div className="num text-[11px] text-ink-400">{tf.seconds}s per candle</div>
                </button>
              ))}
            </div>
            {activeMeta && (
              <p className="mt-3 text-xs text-ink-400">
                Showing {candles.length} candles at {activeMeta.label} resolution.
              </p>
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}
