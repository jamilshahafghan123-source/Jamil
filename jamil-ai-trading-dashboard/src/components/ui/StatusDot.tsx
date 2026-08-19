import type { ServiceState } from '@/types';
import { cn } from '@/lib/cn';

const DOT: Record<ServiceState, string> = {
  connected: 'bg-bull-500 text-bull-500',
  degraded: 'bg-warn-400 text-warn-400',
  disconnected: 'bg-bear-500 text-bear-500',
  checking: 'bg-ink-400 text-ink-400',
};

export function StatusDot({ state, pulse = true }: { state: ServiceState; pulse?: boolean }) {
  return (
    <span
      className={cn(
        'relative inline-block h-2 w-2 shrink-0 rounded-full',
        DOT[state],
        pulse && state !== 'disconnected' && 'pulse-ring',
      )}
      aria-hidden="true"
    />
  );
}
