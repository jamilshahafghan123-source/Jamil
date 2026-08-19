import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { Menu, X } from 'lucide-react';
import { useDashboard } from '@/context/dashboardContext';
import { Badge, StatusDot } from '@/components/ui';
import { cn } from '@/lib/cn';
import { formatClock } from '@/lib/format';
import { Logo } from './Logo';
import { NAV_ITEMS } from './navigation';

export function Header() {
  const { connection, lastMarketDataAt } = useDashboard();
  const [open, setOpen] = useState(false);

  const bridge = connection.services.find((s) => s.id === 'mt5-bridge');
  const bridgeState = bridge?.state ?? 'checking';
  const bridgeLabel =
    bridgeState === 'connected'
      ? 'MT5 Connected'
      : bridgeState === 'checking'
        ? 'MT5 Checking…'
        : bridgeState === 'degraded'
          ? 'MT5 Degraded'
          : 'MT5 Disconnected';

  return (
    <header className="sticky top-0 z-40 border-b border-base-700/80 bg-base-950/85 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1800px] items-center gap-3 px-3 sm:px-5">
        <NavLink to="/" className="shrink-0" aria-label="Jamil AI Trading — dashboard home">
          <Logo />
        </NavLink>

        <nav className="ml-4 hidden flex-1 items-center gap-1 lg:flex" aria-label="Primary">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-base-800 text-ink-100 ring-1 ring-base-600 ring-inset'
                    : 'text-ink-400 hover:bg-base-850 hover:text-ink-200',
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2 lg:ml-0">
          <Badge tone="warn" size="md" className="hidden sm:inline-flex">
            Demo mode
          </Badge>

          <div
            className="hidden items-center gap-2 rounded-lg border border-base-700 bg-base-900/70 px-2.5 py-1.5 md:flex"
            title={bridge?.detail}
          >
            <StatusDot state={bridgeState} />
            <span
              className={cn(
                'text-xs font-semibold whitespace-nowrap',
                bridgeState === 'connected' ? 'text-bull-400' : 'text-ink-300',
              )}
            >
              {bridgeLabel}
            </span>
            <span className="num hidden text-[11px] text-ink-500 xl:inline">
              {formatClock(lastMarketDataAt)}
            </span>
          </div>

          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-label={open ? 'Close navigation menu' : 'Open navigation menu'}
            className="grid h-9 w-9 place-items-center rounded-lg border border-base-700 bg-base-900/70 text-ink-300 hover:text-ink-100 lg:hidden"
          >
            {open ? <X className="h-4.5 w-4.5" /> : <Menu className="h-4.5 w-4.5" />}
          </button>
        </div>
      </div>

      {open && (
        <nav className="border-t border-base-700/80 bg-base-900/95 px-3 py-2 lg:hidden" aria-label="Mobile">
          <div className="grid gap-1 sm:grid-cols-2">
            {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium',
                    isActive ? 'bg-base-800 text-ink-100' : 'text-ink-300 hover:bg-base-850',
                  )
                }
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
          </div>
          <div className="mt-2 flex items-center gap-2 px-1 pb-1 sm:hidden">
            <Badge tone="warn">Demo mode</Badge>
            <div className="flex items-center gap-1.5">
              <StatusDot state={bridgeState} />
              <span className="text-xs text-ink-300">{bridgeLabel}</span>
            </div>
          </div>
        </nav>
      )}
    </header>
  );
}
