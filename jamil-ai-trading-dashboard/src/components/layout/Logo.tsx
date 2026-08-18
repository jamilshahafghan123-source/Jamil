export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="relative grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-gold-400/25 to-gold-600/10 ring-1 ring-gold-400/30 ring-inset">
        <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden="true">
          <path
            d="M4 17 8.5 6.5 12 14l3.5-7.5L20 17"
            fill="none"
            stroke="currentColor"
            className="text-gold-400"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      {!compact && (
        <span className="leading-tight">
          <span className="block text-sm font-bold tracking-tight text-ink-100">Jamil AI Trading</span>
          <span className="block text-[10px] font-medium tracking-[0.18em] text-gold-500 uppercase">
            Gold Desk
          </span>
        </span>
      )}
    </div>
  );
}
