import { Landmark, TrendingDown, TrendingUp } from 'lucide-react';
import type { AccountSnapshot, DataSource } from '@/types';
import { Badge, DataSourceTag, Meter, Panel, SkeletonRows, Stat } from '@/components/ui';
import { cn } from '@/lib/cn';
import { clamp, formatMoney, formatPercent, formatSignedMoney } from '@/lib/format';

export function AccountPanel({
  account,
  source,
}: {
  account: AccountSnapshot | null;
  source: DataSource;
}) {
  if (!account) {
    return (
      <Panel icon={<Landmark className="h-4.5 w-4.5" />} title="Account">
        <SkeletonRows rows={5} />
      </Panel>
    );
  }

  const up = account.todayPnl >= 0;
  const marginUsedPct =
    account.equity > 0 ? clamp((account.margin / account.equity) * 100, 0, 100) : 0;

  return (
    <Panel
      icon={<Landmark className="h-4.5 w-4.5" />}
      title="Account"
      subtitle={`${account.broker} · #${account.login} · 1:${account.leverage}`}
      actions={
        <>
          <Badge tone={account.accountType === 'demo' ? 'warn' : 'bear'} size="md">
            {account.accountType} account
          </Badge>
          <DataSourceTag source={source} />
        </>
      }
      footer={
        <span>
          Balances are simulated for the demo environment. No funds, real or otherwise, are at risk
          in this build.
        </span>
      }
    >
      <div className="rounded-xl border border-base-700 bg-base-900/50 p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <Stat
            label="Equity"
            value={formatMoney(account.equity, account.currency)}
            size="lg"
            hint={`Balance ${formatMoney(account.balance, account.currency)}`}
          />
          <div
            className={cn(
              'flex items-center gap-2 rounded-lg px-3 py-2 ring-1 ring-inset',
              up ? 'bg-bull-500/10 ring-bull-500/25' : 'bg-bear-500/10 ring-bear-500/25',
            )}
          >
            {up ? (
              <TrendingUp className="h-4.5 w-4.5 text-bull-400" />
            ) : (
              <TrendingDown className="h-4.5 w-4.5 text-bear-400" />
            )}
            <div className="leading-tight">
              <div className="text-[10px] font-medium tracking-wider text-ink-400 uppercase">
                Today&rsquo;s P/L
              </div>
              <div className={cn('num text-base font-bold', up ? 'text-bull-400' : 'text-bear-400')}>
                {formatSignedMoney(account.todayPnl, account.currency)}
                <span className="ml-1.5 text-xs font-semibold opacity-80">
                  {formatPercent(account.todayPnlPercent)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded-lg border border-base-700 bg-base-900/50 px-3 py-2.5">
          <Stat label="Balance" value={formatMoney(account.balance, account.currency)} size="sm" />
        </div>
        <div className="rounded-lg border border-base-700 bg-base-900/50 px-3 py-2.5">
          <Stat
            label="Free margin"
            value={formatMoney(account.freeMargin, account.currency)}
            size="sm"
          />
        </div>
        <div className="rounded-lg border border-base-700 bg-base-900/50 px-3 py-2.5">
          <Stat label="Margin" value={formatMoney(account.margin, account.currency)} size="sm" />
        </div>
        <div className="rounded-lg border border-base-700 bg-base-900/50 px-3 py-2.5">
          <Stat label="Open positions" value={account.openPositions} size="sm" />
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-baseline justify-between text-[11px] font-medium tracking-wider text-ink-400 uppercase">
          <span>Margin used</span>
          <span className="num text-ink-200">
            {marginUsedPct.toFixed(1)}%
            {account.marginLevel !== null && (
              <span className="ml-2 text-ink-500">level {account.marginLevel.toFixed(0)}%</span>
            )}
          </span>
        </div>
        <Meter
          value={marginUsedPct}
          tone={marginUsedPct > 60 ? 'bear' : marginUsedPct > 30 ? 'warn' : 'bull'}
          className="mt-2"
        />
      </div>
    </Panel>
  );
}
