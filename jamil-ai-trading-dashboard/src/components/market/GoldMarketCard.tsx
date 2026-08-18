import { useEffect, useRef, useState } from 'react';
import { ArrowDownRight, ArrowUpRight, Clock, Coins, Minus } from 'lucide-react';
import type { DataSource, MarketSession, Quote } from '@/types';
import { Badge, DataSourceTag, Panel, Skeleton, Stat } from '@/components/ui';
import { cn } from '@/lib/cn';
import { clamp, formatClock, formatPercent, formatPrice, formatRelative } from '@/lib/format';

const SESSION_LABEL: Record<MarketSession, { text: string; tone: 'bull' | 'bear' | 'warn' }> = {
  open: { text: 'Market open', tone: 'bull' },
  closed: { text: 'Market closed', tone: 'bear' },
  'pre-market': { text: 'Pre-market', tone: 'warn' },
  'after-hours': { text: 'Broker break', tone: 'warn' },
};

/** Adds a brief green/red wash whenever the value ticks. */
function useFlash(value: number | undefined) {
  const [flash, setFlash] = useState<'' | 'flash-up' | 'flash-down'>('');
  const previous = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (value === undefined) return;
    const prev = previous.current;
    previous.current = value;
    if (prev === undefined || prev === value) return;
    setFlash(value > prev ? 'flash-up' : 'flash-down');
    const id = window.setTimeout(() => setFlash(''), 620);
    return () => window.clearTimeout(id);
  }, [value]);

  return flash;
}

export function GoldMarketCard({
  quote,
  source,
  lastUpdatedAt,
}: {
  quote: Quote | null;
  source: DataSource;
  lastUpdatedAt: string | null;
}) {
  const priceFlash = useFlash(quote?.price);
  const bidFlash = useFlash(quote?.bid);
  const askFlash = useFlash(quote?.ask);
  const [, forceTick] = useState(0);

  // Keeps the "x seconds ago" freshness label moving between quote updates.
  useEffect(() => {
    const id = window.setInterval(() => forceTick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  if (!quote) {
    return (
      <Panel title="GOLD" subtitle="XAUUSD">
        <div className="space-y-3">
          <Skeleton className="h-10 w-48" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      </Panel>
    );
  }

  const up = quote.dayChange >= 0;
  const session = SESSION_LABEL[quote.session];
  const rangePosition =
    quote.dayHigh > quote.dayLow
      ? clamp(((quote.price - quote.dayLow) / (quote.dayHigh - quote.dayLow)) * 100, 0, 100)
      : 50;

  return (
    <Panel
      icon={<Coins className="h-4.5 w-4.5" />}
      title={
        <span className="flex items-center gap-2">
          GOLD
          <span className="num text-xs font-medium text-ink-400">{quote.symbol}</span>
        </span>
      }
      subtitle={quote.description}
      actions={
        <>
          <Badge tone={session.tone}>{session.text}</Badge>
          <DataSourceTag source={source} />
        </>
      }
      footer={
        <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="inline-flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5" />
            Last update <span className="num text-ink-300">{formatClock(quote.updatedAt)}</span>
            <span className="text-ink-500">({formatRelative(lastUpdatedAt)})</span>
          </span>
          <span className="text-ink-500">
            Prev. close <span className="num text-ink-300">{formatPrice(quote.previousClose)}</span>
          </span>
        </span>
      }
    >
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div>
          <div className="text-[11px] font-medium tracking-wider text-ink-400 uppercase">
            Live price (mid)
          </div>
          <div
            className={cn(
              'num mt-1 rounded-md px-1 text-4xl leading-none font-bold text-ink-100 sm:text-5xl',
              priceFlash,
            )}
          >
            {formatPrice(quote.price, quote.digits)}
            <span className="ml-2 align-super text-sm font-medium text-ink-400">USD</span>
          </div>
        </div>

        <div
          className={cn(
            'flex items-center gap-2 rounded-lg px-3 py-2 ring-1 ring-inset',
            up ? 'bg-bull-500/10 ring-bull-500/25' : 'bg-bear-500/10 ring-bear-500/25',
          )}
        >
          {quote.dayChange === 0 ? (
            <Minus className="h-5 w-5 text-ink-400" />
          ) : up ? (
            <ArrowUpRight className="h-5 w-5 text-bull-400" />
          ) : (
            <ArrowDownRight className="h-5 w-5 text-bear-400" />
          )}
          <div className="leading-tight">
            <div className={cn('num text-lg font-bold', up ? 'text-bull-400' : 'text-bear-400')}>
              {up ? '+' : '−'}
              {formatPrice(Math.abs(quote.dayChange), quote.digits)}
            </div>
            <div className={cn('num text-xs font-semibold', up ? 'text-bull-400/80' : 'text-bear-400/80')}>
              {formatPercent(quote.dayChangePercent)} today
            </div>
          </div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className={cn('rounded-lg border border-base-700 bg-base-900/60 px-3 py-2', bidFlash)}>
          <Stat label="Bid" value={formatPrice(quote.bid, quote.digits)} tone="bear" size="md" />
        </div>
        <div className={cn('rounded-lg border border-base-700 bg-base-900/60 px-3 py-2', askFlash)}>
          <Stat label="Ask" value={formatPrice(quote.ask, quote.digits)} tone="bull" size="md" />
        </div>
        <div className="rounded-lg border border-base-700 bg-base-900/60 px-3 py-2">
          <Stat
            label="Spread"
            value={`${quote.spreadPoints}`}
            hint={`${formatPrice(quote.ask - quote.bid, quote.digits)} USD`}
            tone="gold"
            size="md"
          />
        </div>
        <div className="rounded-lg border border-base-700 bg-base-900/60 px-3 py-2">
          <Stat label="Day open" value={formatPrice(quote.dayOpen, quote.digits)} size="md" />
        </div>
      </div>

      <div className="mt-5">
        <div className="flex items-center justify-between text-[11px] font-medium tracking-wider text-ink-400 uppercase">
          <span>
            Low <span className="num text-ink-200">{formatPrice(quote.dayLow, quote.digits)}</span>
          </span>
          <span>Daily range</span>
          <span>
            High <span className="num text-ink-200">{formatPrice(quote.dayHigh, quote.digits)}</span>
          </span>
        </div>
        <div className="relative mt-2 h-1.5 rounded-full bg-gradient-to-r from-bear-600/50 via-base-700 to-bull-600/50">
          <span
            className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-base-950 bg-gold-400 transition-[left] duration-500"
            style={{ left: `${rangePosition}%` }}
            aria-hidden="true"
          />
        </div>
      </div>
    </Panel>
  );
}
