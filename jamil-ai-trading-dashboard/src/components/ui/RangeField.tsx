import { cn } from '@/lib/cn';

interface RangeFieldProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  hint?: string;
  disabled?: boolean;
  onChange: (value: number) => void;
}

/** Labelled slider used by the risk management controls. */
export function RangeField({
  label,
  value,
  min,
  max,
  step,
  unit,
  hint,
  disabled,
  onChange,
}: RangeFieldProps) {
  const id = `range-${label.replace(/\s+/g, '-').toLowerCase()}`;
  return (
    <div className={cn(disabled && 'opacity-60')}>
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium text-ink-200">
          {label}
        </label>
        <span className="num text-sm font-semibold text-gold-300">
          {value}
          {unit}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-2 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-base-750 accent-gold-400 disabled:cursor-not-allowed"
      />
      {hint && <p className="mt-1.5 text-xs text-ink-400">{hint}</p>}
    </div>
  );
}
