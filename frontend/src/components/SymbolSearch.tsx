import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import type { InstrumentInfo } from "../lib/types";

/**
 * Global symbol search (section 5) and watchlist (section 6).
 *
 * The honesty rule runs through both: only an instrument the platform can
 * actually price shows a number. Everything else shows its status, so a
 * customer searching for TSLA is told it is coming rather than being shown
 * an invented quote or being told the symbol does not exist.
 */

const CLASS_ORDER = [
  "METALS", "FOREX", "CRYPTO", "INDICES", "FUTURES", "ETFS", "STOCKS", "ENERGY",
] as const;

const CLASS_LABEL: Record<string, string> = {
  METALS: "Metals", FOREX: "Forex", CRYPTO: "Crypto", INDICES: "Indices",
  FUTURES: "Futures", ETFS: "ETFs", STOCKS: "Stocks", ENERGY: "Energy",
};

const STATUS_LABEL: Record<string, string> = {
  ENABLED: "Live",
  DATA_ONLY: "Chart only",
  COMING_SOON: "Coming soon",
  UNSUPPORTED: "Unsupported",
  DISABLED: "Unavailable",
};

const FAVOURITES_KEY = "jgold.watchlist";

function readFavourites(): string[] {
  try {
    const raw = localStorage.getItem(FAVOURITES_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? parsed.filter((s) => typeof s === "string") : [];
  } catch {
    // A private window or blocked storage is not an error worth surfacing:
    // the watchlist simply starts empty.
    return [];
  }
}

function writeFavourites(symbols: string[]) {
  try {
    localStorage.setItem(FAVOURITES_KEY, JSON.stringify(symbols));
  } catch {
    /* nothing to do; the list stays in memory for this session */
  }
}

export function useWatchlist() {
  const [favourites, setFavourites] = useState<string[]>(readFavourites);

  const toggle = (symbol: string) =>
    setFavourites((current) => {
      const next = current.includes(symbol)
        ? current.filter((s) => s !== symbol)
        : [...current, symbol];
      writeFavourites(next);
      return next;
    });

  return { favourites, toggle, isFavourite: (s: string) => favourites.includes(s) };
}

export function SymbolSearch({
  open,
  onClose,
  onPick,
  current,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (symbol: string) => void;
  current: string;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<InstrumentInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const { favourites, toggle, isFavourite } = useWatchlist();

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  // One in-flight search; a fast typist must not have an older response
  // land on top of a newer one.
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setBusy(true);
      try {
        const res = await api.searchInstruments(query, controller.signal);
        setResults(res.results);
        setError(null);
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Search unavailable");
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }, 180);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, open]);

  const grouped = useMemo(() => {
    const out = new Map<string, InstrumentInfo[]>();
    for (const item of results) {
      const list = out.get(item.asset_class) ?? [];
      list.push(item);
      out.set(item.asset_class, list);
    }
    return [...out.entries()].sort(
      (a, b) => CLASS_ORDER.indexOf(a[0] as never) - CLASS_ORDER.indexOf(b[0] as never),
    );
  }, [results]);

  if (!open) return null;

  const favouriteRows = results.filter((r) => favourites.includes(r.symbol));

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true"
         aria-label="Symbol search" onClick={onClose}>
      <div className="modal jg-symbol-modal" onClick={(e) => e.stopPropagation()}>
        <header className="jg-symbol-head">
          <input
            ref={input}
            className="jg-symbol-input"
            placeholder="Search symbol, name or market — XAUUSD, gold, tesla, nasdaq"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search symbols"
          />
          <button type="button" className="btn sm" onClick={onClose}>Close</button>
        </header>

        {error && <p className="jg-ws-error">{error}</p>}

        <div className="jg-symbol-body">
          {busy && results.length === 0 && <p className="jg-cc-note">Searching…</p>}
          {!busy && results.length === 0 && (
            <p className="jg-cc-note">No symbol matches “{query}”.</p>
          )}

          {favouriteRows.length > 0 && (
            <section>
              <h4 className="jg-symbol-group">Watchlist</h4>
              {favouriteRows.map((item) => (
                <Row key={`fav-${item.symbol}`} item={item} current={current}
                     onPick={onPick} onToggle={toggle} favourite />
              ))}
            </section>
          )}

          {grouped.map(([assetClass, items]) => (
            <section key={assetClass}>
              <h4 className="jg-symbol-group">
                {CLASS_LABEL[assetClass] ?? assetClass}
              </h4>
              {items.map((item) => (
                <Row key={item.symbol} item={item} current={current}
                     onPick={onPick} onToggle={toggle}
                     favourite={isFavourite(item.symbol)} />
              ))}
            </section>
          ))}
        </div>

        <footer className="jg-symbol-foot">
          Only markets with a live J Gold AI feed show a price. Everything else
          shows its status — no figure is estimated or invented.
        </footer>
      </div>
    </div>
  );
}

function Row({
  item, current, onPick, onToggle, favourite,
}: {
  item: InstrumentInfo;
  current: string;
  onPick: (symbol: string) => void;
  onToggle: (symbol: string) => void;
  favourite: boolean;
}) {
  return (
    <div className={item.symbol === current ? "jg-symbol-row current" : "jg-symbol-row"}>
      <button
        type="button"
        className="jg-symbol-star"
        aria-label={favourite ? `Remove ${item.symbol} from watchlist`
                              : `Add ${item.symbol} to watchlist`}
        aria-pressed={favourite}
        onClick={() => onToggle(item.symbol)}
      >
        {favourite ? "★" : "☆"}
      </button>
      <button
        type="button"
        className="jg-symbol-pick"
        disabled={!item.priceable}
        title={item.priceable ? `Open ${item.symbol}`
                              : `${item.symbol} has no market data yet`}
        onClick={() => item.priceable && onPick(item.symbol)}
      >
        <span className="jg-symbol-code">{item.symbol}</span>
        <span className="jg-symbol-name">{item.display_name}</span>
        <span className={`jg-symbol-status ${item.status.toLowerCase()}`}>
          {STATUS_LABEL[item.status] ?? item.status}
        </span>
      </button>
    </div>
  );
}
