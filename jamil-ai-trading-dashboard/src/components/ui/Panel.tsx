import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface PanelProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}

/** The standard framed surface used by every dashboard section. */
export function Panel({
  title,
  subtitle,
  icon,
  actions,
  footer,
  className,
  bodyClassName,
  children,
}: PanelProps) {
  return (
    <section className={cn('panel flex flex-col overflow-hidden', className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-base-700/70 px-4 py-3 sm:px-5">
          {icon && <span className="text-gold-400">{icon}</span>}
          {/* min-w keeps the heading readable and pushes the action chips onto
              their own line instead of truncating the title. */}
          <div className="min-w-[9rem] flex-1">
            {title && (
              <h2 className="text-sm font-semibold tracking-wide text-balance text-ink-100">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 truncate text-xs text-ink-400">{subtitle}</p>}
          </div>
          {actions && (
            <div className="flex flex-wrap items-center justify-end gap-2">{actions}</div>
          )}
        </header>
      )}
      <div className={cn('flex-1 p-4 sm:p-5', bodyClassName)}>{children}</div>
      {footer && (
        <footer className="border-t border-base-700/70 px-4 py-2.5 text-xs text-ink-400 sm:px-5">
          {footer}
        </footer>
      )}
    </section>
  );
}
