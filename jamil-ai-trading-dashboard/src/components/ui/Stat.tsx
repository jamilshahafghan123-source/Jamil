import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface StatProps {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: 'default' | 'bull' | 'bear' | 'gold' | 'muted';
  align?: 'left' | 'right';
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const TONE_CLASS = {
  default: 'text-ink-100',
  bull: 'text-bull-400',
  bear: 'text-bear-400',
  gold: 'text-gold-300',
  muted: 'text-ink-300',
};

const SIZE_CLASS = {
  sm: 'text-sm',
  md: 'text-lg',
  lg: 'text-2xl',
};

/** Label + value pair used across the account, risk and market panels. */
export function Stat({
  label,
  value,
  hint,
  tone = 'default',
  align = 'left',
  size = 'md',
  className,
}: StatProps) {
  return (
    <div className={cn('min-w-0', align === 'right' && 'text-right', className)}>
      <div className="text-[11px] font-medium tracking-wider text-ink-400 uppercase">{label}</div>
      <div className={cn('num mt-1 font-semibold', SIZE_CLASS[size], TONE_CLASS[tone])}>{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-ink-400">{hint}</div>}
    </div>
  );
}
