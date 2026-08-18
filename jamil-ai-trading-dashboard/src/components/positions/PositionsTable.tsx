import { ArrowDown, ArrowUp, Inbox, Wallet } from 'lucide-react';
import type { DataSource, Position } from '@/types';
import { Badge, DataSourceTag, EmptyState, Panel, SkeletonRows } from '@/components/ui';
import { cn } from '@/lib/cn';
import { formatLots, formatPercent, formatPrice, formatSignedMoney } from '@/lib/format';

const COLUMNS = [
  'Symbol',
  'Direction',
  'Volume',
  'Entry',
  'Current',
  'Stop loss',
  'Take profit',
  'P/L',
  'Status',
] as const;

export function PositionsTable({
  positions,
  source,
  loading = false,
  title = 'Open positions',
}: {
  positions: Position[];
  source: DataSource;
  loading?: boolean;
  title?: string;
}) {
  const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0);

  return (
    <Panel
      icon={<Wallet className="h-4.5 w-4.5" />}
      title={title}
      subtitle={`${positions.length} position${positions.length === 1 ? '' : 's'} · simulated fills`}
      bodyClassName="p-0 sm:p-0"
      actions={
        <>
          <span
            className={cn(
              'num rounded-md px-2 py-1 text-xs font-bold ring-1 ring-inset',
              totalPnl >= 0
                ? 'bg-bull-500/10 text-bull-400 ring-bull-500/25'
                : 'bg-bear-500/10 text-bear-400 ring-bear-500/25',
            )}
          >
            {formatSignedMoney(totalPnl)}
          </span>
          <DataSourceTag source={source} />
        </>
      }
      footer={
        <span>
          Read-only view. Order placement and position management are disabled in the demo build.
        </span>
      }
    >
      {loading ? (
        <div className="p-4 sm:p-5">
          <SkeletonRows rows={4} />
        </div>
      ) : positions.length === 0 ? (
        <EmptyState
          icon={<Inbox className="h-7 w-7" />}
          title="No open positions"
          description="Simulated positions will appear here once the demo account holds exposure."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[54rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-base-700 text-left">
                {COLUMNS.map((column, i) => (
                  <th
                    key={column}
                    scope="col"
                    className={cn(
                      'px-4 py-2.5 text-[10px] font-semibold tracking-wider text-ink-400 uppercase whitespace-nowrap',
                      i >= 2 && i <= 7 && 'text-right',
                      i === 8 && 'text-right',
                    )}
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => {
                const isBuy = position.direction === 'buy';
                const profitable = position.pnl >= 0;
                return (
                  <tr
                    key={position.id}
                    className="border-b border-base-800/80 transition-colors last:border-0 hover:bg-base-800/40"
                  >
                    <td className="px-4 py-3">
                      <div className="font-semibold text-ink-100">{position.symbol}</div>
                      <div className="num text-[11px] text-ink-500">#{position.id}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          'inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-bold uppercase ring-1 ring-inset',
                          isBuy
                            ? 'bg-bull-500/10 text-bull-400 ring-bull-500/25'
                            : 'bg-bear-500/10 text-bear-400 ring-bear-500/25',
                        )}
                      >
                        {isBuy ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
                        {position.direction}
                      </span>
                    </td>
                    <td className="num px-4 py-3 text-right text-ink-200">
                      {formatLots(position.volume)}
                    </td>
                    <td className="num px-4 py-3 text-right text-ink-200">
                      {formatPrice(position.entryPrice)}
                    </td>
                    <td className="num px-4 py-3 text-right font-semibold text-ink-100">
                      {formatPrice(position.currentPrice)}
                    </td>
                    <td className="num px-4 py-3 text-right">
                      {position.stopLoss === null ? (
                        <span className="text-[11px] font-semibold text-warn-400">Not set</span>
                      ) : (
                        <span className="text-bear-400/90">{formatPrice(position.stopLoss)}</span>
                      )}
                    </td>
                    <td className="num px-4 py-3 text-right">
                      {position.takeProfit === null ? (
                        <span className="text-ink-500">—</span>
                      ) : (
                        <span className="text-bull-400/90">{formatPrice(position.takeProfit)}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div
                        className={cn(
                          'num font-bold',
                          profitable ? 'text-bull-400' : 'text-bear-400',
                        )}
                      >
                        {formatSignedMoney(position.pnl)}
                      </div>
                      <div
                        className={cn(
                          'num text-[11px]',
                          profitable ? 'text-bull-400/70' : 'text-bear-400/70',
                        )}
                      >
                        {formatPercent(position.pnlPercent)}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Badge tone={position.status === 'open' ? 'info' : 'muted'}>
                        {position.status}
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
  );
}
