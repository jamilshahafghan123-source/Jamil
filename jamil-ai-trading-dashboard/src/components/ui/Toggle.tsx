import { Lock } from 'lucide-react';
import { cn } from '@/lib/cn';

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  /** Locked toggles cannot be changed and explain why. */
  locked?: boolean;
  lockReason?: string;
}

export function Toggle({ checked, onChange, label, description, locked, lockReason }: ToggleProps) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 text-sm font-medium text-ink-100">
          {label}
          {locked && <Lock className="h-3.5 w-3.5 text-ink-400" aria-hidden="true" />}
        </div>
        {(locked ? lockReason : description) && (
          <p className="mt-0.5 text-xs text-ink-400">{locked ? lockReason : description}</p>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={locked}
        onClick={() => !locked && onChange(!checked)}
        className={cn(
          'relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors',
          checked ? 'bg-bull-600' : 'bg-base-700',
          locked ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-ink-100 transition-transform',
            checked && 'translate-x-4',
          )}
        />
      </button>
    </div>
  );
}
