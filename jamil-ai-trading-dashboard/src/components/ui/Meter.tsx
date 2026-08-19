import { cn } from '@/lib/cn';
import { clamp } from '@/lib/format';

interface MeterProps {
  /** 0..100 */
  value: number;
  tone?: 'gold' | 'bull' | 'bear' | 'info' | 'warn';
  className?: string;
  trackClassName?: string;
}

const FILL: Record<NonNullable<MeterProps['tone']>, string> = {
  gold: 'bg-gradient-to-r from-gold-600 to-gold-400',
  bull: 'bg-gradient-to-r from-bull-600 to-bull-400',
  bear: 'bg-gradient-to-r from-bear-600 to-bear-400',
  info: 'bg-gradient-to-r from-info-400/70 to-info-400',
  warn: 'bg-gradient-to-r from-warn-400/70 to-warn-400',
};

export function Meter({ value, tone = 'gold', className, trackClassName }: MeterProps) {
  const pct = clamp(value, 0, 100);
  return (
    <div
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-base-750', trackClassName)}
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cn('h-full rounded-full transition-[width] duration-500', FILL[tone], className)}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
