import { useMemo, useState } from 'react';
import { History, Inbox } from 'lucide-react';
import { useDashboard } from '@/context/dashboardContext';
import { PageHeading } from '@/components/layout/PageHeading';
import { Badge, DataSourceTag, EmptyState, Panel, Segmented, Stat } from '@/components/ui';
import type { BadgeTone } from '@/components/ui';
import { cn } from '@/lib/cn';
import {
  formatDateTime,
  formatLots,
  formatMoney,
  formatPercent,
  formatPrice,
  formatSignedMoney,
} from '@/lib/format';

type Filter = 'all' | 'wins' | 'losses';

const CLOSE_TONE: Record<string, BadgeTone> = {
  'take-profit': 'bull',
  'stop-loss': 'bear',
  manual: 'muted',
  timeout: 'warn',
};

export function HistoryPage() {
  const { history, source } = useDashboard();
  const [filter, setFilter] = useState<Filter>('all');

  const filtered = useMemo(
    () =>
      history.filter((trade) =>
        filter === 'wins' ? trade.pnl > 0 : filter === 'losses' ? trade.pnl <= 0 : true,
      ),
    [history, filter],
  );

  const stats = useMemo(() => {
    const wins = history.filter((t) => t.pnl > 0);
    const losses = history.filter((t) => t.pnl <= 0);
    const grossWin = wins.reduce((sum, t) => sum + t.pnl, 0);
    const grossLoss = Math.abs(losses.reduce((sum, t) => sum + t.pnl, 0));
    return {
      total: history.length,
      net: history.reduce((sum, t) => sum + t.pnl, 0),
      winRate: history.length ? (wins.length / history.length) * 100 : 0,
      profitFactor: grossLoss > 0 ? grossWin / grossLoss : 0,
      bestTrade: history.reduce((best, t) => Math.max(best, t.pnl), 0),
      worstTrade: history.reduce((worst, t) => Math.min(worst, t.pnl), 0),
    };
  }, [history]);

  return (
    <>
      <PageHeading
        title="History"
        description="Closed demo trades. These are generated sample records, not a record of real executions."
        actions={<DataSourceTag source={source} />}
      />

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {[
          { label: 'Closed trades', value: String(stats.total), tone: 'default' as const },
          {
            label: 'Net P/L',
            value: formatSignedMoney(stats.net),
            tone: stats.net >= 0 ? ('bull' as const) : ('bear' as const),
          },
          { label: 'Win rate', value: `${stats.winRate.toFixed(1)}%`, tone: 'default' as const },
          {
            label: 'Profit factor',
            value: stats.profitFactor ? stats.profitFactor.toFixed(2) : '—',
            tone: 'gold' as const,
          },
          { label: 'Best trade', value: formatMoney(stats.bestTrade), tone: 'bull' as const },
          { label: 'Worst trade', value: formatMoney(stats.worstTrade), tone: 'bear' as const },
        ].map((item) => (
          <div key={item.label} className="panel px-3.5 py-3">
            <Stat label={item.label} value={item.value} tone={item.tone} size="md" />
          </div>
        ))}
      </div>

      <Panel
        icon={<History className="h-4.5 w-4.5" />}
        title="Trade history"
        subtitle={`${filtered.length} of ${history.length} records`}
        bodyClassName="p-0 sm:p-0"
        actions={
          <Segmented
            options={[
              { id: 'all', label: 'All' },
              { id: 'wins', label: 'Wins' },
              { id: 'losses', label: 'Losses' },
            ]}
            value={filter}
            onChange={setFilter}
            ariaLabel="Filter trade history"
          />
        }
        footer={<span>Sample data generated locally for the demo build.</span>}
      >
        {filtered.length === 0 ? (
          <EmptyState icon={<Inbox className="h-7 w-7" />} title="No trades match this filter" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[62rem] border-collapse text-sm">
              <thead>
                <tr className="border-b border-base-700 text-left">
                  {[
                    'Ticket',
                    'Symbol',
                    'Direction',
                    'Volume',
                    'Entry',
                    'Exit',
                    'P/L',
                    'Closed',
                    'Reason',
                  ].map((column, i) => (
                    <th
                      key={column}
                      scope="col"
                      className={cn(
                        'px-4 py-2.5 text-[10px] font-semibold tracking-wider text-ink-400 uppercase whitespace-nowrap',
                        i >= 3 && i <= 6 && 'text-right',
                        i === 8 && 'text-right',
                      )}
                    >
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((trade) => {
                  const profitable = trade.pnl > 0;
                  return (
                    <tr
                      key={trade.id}
                      className="border-b border-base-800/80 transition-colors last:border-0 hover:bg-base-800/40"
                    >
                      <td className="num px-4 py-2.5 text-ink-400">#{trade.id}</td>
                      <td className="px-4 py-2.5 font-semibold text-ink-100">{trade.symbol}</td>
                      <td className="px-4 py-2.5">
                        <span
                          className={cn(
                            'text-[11px] font-bold uppercase',
                            trade.direction === 'buy' ? 'text-bull-400' : 'text-bear-400',
                          )}
                        >
                          {trade.direction}
                        </span>
                      </td>
                      <td className="num px-4 py-2.5 text-right text-ink-200">
                        {formatLots(trade.volume)}
                      </td>
                      <td className="num px-4 py-2.5 text-right text-ink-300">
                        {formatPrice(trade.entryPrice)}
                      </td>
                      <td className="num px-4 py-2.5 text-right text-ink-300">
                        {formatPrice(trade.exitPrice)}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <div
                          className={cn(
                            'num font-bold',
                            profitable ? 'text-bull-400' : 'text-bear-400',
                          )}
                        >
                          {formatSignedMoney(trade.pnl)}
                        </div>
                        <div
                          className={cn(
                            'num text-[11px]',
                            profitable ? 'text-bull-400/70' : 'text-bear-400/70',
                          )}
                        >
                          {formatPercent(trade.pnlPercent)}
                        </div>
                      </td>
                      <td className="num px-4 py-2.5 text-[11px] whitespace-nowrap text-ink-400">
                        {formatDateTime(trade.closedAt)}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <Badge tone={CLOSE_TONE[trade.closeReason] ?? 'muted'}>
                          {trade.closeReason.replace('-', ' ')}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}
