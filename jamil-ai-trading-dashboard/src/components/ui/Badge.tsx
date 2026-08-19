import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type BadgeTone = 'neutral' | 'gold' | 'bull' | 'bear' | 'info' | 'warn' | 'muted';

const TONES: Record<BadgeTone, string> = {
  neutral: 'bg-base-750 text-ink-200 ring-base-600',
  gold: 'bg-gold-400/12 text-gold-300 ring-gold-400/35',
  bull: 'bg-bull-500/12 text-bull-400 ring-bull-500/35',
  bear: 'bg-bear-500/12 text-bear-400 ring-bear-500/35',
  info: 'bg-info-400/12 text-info-400 ring-info-400/35',
  warn: 'bg-warn-400/12 text-warn-400 ring-warn-400/35',
  muted: 'bg-base-800 text-ink-400 ring-base-700',
};

interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
  icon?: ReactNode;
  className?: string;
  size?: 'sm' | 'md';
}

export function Badge({ tone = 'neutral', children, icon, className, size = 'sm' }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md font-semibold tracking-wide uppercase ring-1 ring-inset whitespace-nowrap',
        size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-xs',
        TONES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}
