import { AlertOctagon, Link2, RadioTower } from 'lucide-react';
import type { ConnectionStatus, ServiceState } from '@/types';
import { Badge, Panel, StatusDot } from '@/components/ui';
import type { BadgeTone } from '@/components/ui';
import { cn } from '@/lib/cn';
import { formatClock, formatRelative } from '@/lib/format';

const STATE_TONE: Record<ServiceState, BadgeTone> = {
  connected: 'bull',
  degraded: 'warn',
  disconnected: 'bear',
  checking: 'muted',
};

const STATE_LABEL: Record<ServiceState, string> = {
  connected: 'Connected',
  degraded: 'Degraded',
  disconnected: 'Disconnected',
  checking: 'Checking',
};

export function ConnectionPanel({
  connection,
  lastMarketDataAt,
  errors,
}: {
  connection: ConnectionStatus;
  lastMarketDataAt: string | null;
  errors: { at: string; service: string; message: string }[];
}) {
  return (
    <Panel
      icon={<RadioTower className="h-4.5 w-4.5" />}
      title="Connection status"
      subtitle="Website → Backend API → MT5 Bridge → MetaTrader 5"
      footer={
        <span className="flex items-center gap-1.5">
          <Link2 className="h-3.5 w-3.5" />
          The browser never connects to MetaTrader 5 directly.
        </span>
      }
    >
      <ul className="space-y-2">
        {connection.services.map((service) => (
          <li
            key={service.id}
            className="flex items-center gap-3 rounded-lg border border-base-700 bg-base-900/50 px-3 py-2.5"
          >
            <StatusDot state={service.state} />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-ink-100">{service.label}</div>
              <div className="truncate text-[11px] text-ink-400" title={service.detail}>
                {service.detail}
              </div>
            </div>
            {service.latencyMs !== null && (
              <span className="num hidden text-[11px] text-ink-500 sm:inline">
                {service.latencyMs}ms
              </span>
            )}
            <Badge tone={STATE_TONE[service.state]}>{STATE_LABEL[service.state]}</Badge>
          </li>
        ))}
      </ul>

      <div className="mt-3 flex items-center justify-between rounded-lg border border-base-700 bg-base-900/50 px-3 py-2.5">
        <span className="text-[11px] font-medium tracking-wider text-ink-400 uppercase">
          Last market-data update
        </span>
        <span className="num text-sm font-semibold text-ink-100">
          {formatClock(lastMarketDataAt)}
          <span className="ml-2 text-[11px] font-normal text-ink-500">
            {formatRelative(lastMarketDataAt)}
          </span>
        </span>
      </div>

      <div className="mt-3">
        <div className="flex items-center gap-1.5 text-[11px] font-medium tracking-wider text-ink-400 uppercase">
          <AlertOctagon className="h-3.5 w-3.5" />
          Connection errors
        </div>
        {errors.length === 0 ? (
          <p className="mt-2 rounded-lg border border-base-700 bg-base-900/50 px-3 py-2.5 text-xs text-ink-400">
            No errors recorded in this session.
          </p>
        ) : (
          <ul className="mt-2 max-h-44 space-y-1.5 overflow-y-auto pr-1">
            {errors.map((error, index) => (
              <li
                key={`${error.at}-${index}`}
                className={cn(
                  'rounded-lg border border-bear-500/25 bg-bear-500/8 px-3 py-2 text-xs',
                )}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold text-bear-400">{error.service}</span>
                  <span className="num text-[10px] text-ink-500">{formatClock(error.at)}</span>
                </div>
                <p className="mt-0.5 break-words text-ink-300">{error.message}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
