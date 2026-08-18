import { cn } from '@/lib/cn';

interface SegmentedProps<T extends string> {
  options: { id: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  size?: 'sm' | 'md';
}

/** Compact pill switcher — used for chart timeframes and table filters. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  size = 'sm',
}: SegmentedProps<T>) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="inline-flex items-center gap-0.5 rounded-lg border border-base-700 bg-base-900/70 p-0.5"
    >
      {options.map((option) => {
        const active = option.id === value;
        return (
          <button
            key={option.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.id)}
            className={cn(
              'rounded-md font-semibold transition-colors',
              size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm',
              active
                ? 'bg-gold-400/15 text-gold-300 ring-1 ring-gold-400/30 ring-inset'
                : 'text-ink-400 hover:bg-base-800 hover:text-ink-200',
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
