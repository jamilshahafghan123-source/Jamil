import { ShieldAlert } from 'lucide-react';
import { TRADING_ENABLED, USE_DEMO_DATA } from '@/services';

/**
 * Permanent, non-dismissible statement of what this build is.
 *
 * The dashboard is demo-only during development: no live-money order path
 * exists in the code, and the trading controls stay disabled.
 */
export function SafetyBanner() {
  return (
    <div className="border-b border-warn-400/20 bg-warn-400/8">
      <div className="mx-auto flex max-w-[1800px] items-start gap-2.5 px-3 py-2 sm:px-5">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warn-400" aria-hidden="true" />
        <p className="text-xs leading-relaxed text-ink-300">
          <span className="font-semibold text-warn-400">Demo environment.</span>{' '}
          {USE_DEMO_DATA
            ? 'All prices, balances, positions and AI output on this screen are simulated sample data — not a live market feed.'
            : 'Connected to the backend in demo-account mode.'}{' '}
          Real-money trading is {TRADING_ENABLED ? 'configured but gated' : 'not implemented'} and
          order controls remain disabled.
        </p>
      </div>
    </div>
  );
}
