import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { InstrumentInfo } from "../lib/types";

/**
 * Screener (section 51).
 *
 * A screener ranks instruments by measured values, and this platform has
 * a live feed for exactly one. So rather than print plausible-looking
 * numbers for thirty-four instruments it cannot price, it screens the
 * universe on what it genuinely knows — asset class, status, contract
 * specification — and states plainly that the price and indicator
 * columns are unavailable until more feeds are connected.
 *
 * That is the honest version of this panel. Filling the columns with
 * invented change percentages would make it look finished and make it
 * dangerous.
 */

const CLASS_LABEL: Record<string, string> = {
  METALS: "Metals", FOREX: "Forex", CRYPTO: "Crypto", INDICES: "Indices",
  FUTURES: "Futures", ETFS: "ETFs", STOCKS: "Stocks", ENERGY: "Energy",
};

const STATUS_LABEL: Record<string, string> = {
  ENABLED: "Live", DATA_ONLY: "Chart only", COMING_SOON: "Coming soon",
  UNSUPPORTED: "Unsupported", DISABLED: "Unavailable",
};

export function ScreenerPanel({ currentSymbol }: { currentSymbol: string }) {
  const [rows, setRows] = useState<InstrumentInfo[]>([]);
  const [assetClass, setAssetClass] = useState("ALL");
  const [status, setStatus] = useState("ALL");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.searchInstruments("")
      .then((r) => setRows(r.results))
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Screener unavailable"));
  }, []);

  const classes = useMemo(
    () => [...new Set(rows.map((r) => r.asset_class))].sort(),
    [rows],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (assetClass !== "ALL" && row.asset_class !== assetClass) return false;
      if (status === "LIVE" && !row.priceable) return false;
      if (status === "PLANNED" && row.priceable) return false;
      if (q && !`${row.symbol} ${row.display_name}`.toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
  }, [rows, assetClass, status, query]);

  const liveCount = rows.filter((r) => r.priceable).length;

  if (error) return <p className="jg-ws-error">{error}</p>;

  return (
    <div className="jg-screener">
      <div className="jg-screener-filters">
        <input
          placeholder="Filter by symbol or name"
          value={query}
          aria-label="Filter instruments"
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={assetClass} aria-label="Asset class"
                onChange={(e) => setAssetClass(e.target.value)}>
          <option value="ALL">All asset classes</option>
          {classes.map((c) => (
            <option key={c} value={c}>{CLASS_LABEL[c] ?? c}</option>
          ))}
        </select>
        <select value={status} aria-label="Data status"
                onChange={(e) => setStatus(e.target.value)}>
          <option value="ALL">Any status</option>
          <option value="LIVE">Live data only</option>
          <option value="PLANNED">Not yet live</option>
        </select>
      </div>

      <p className="jg-screener-note">
        {liveCount} of {rows.length} instruments have a live feed. Price,
        change and indicator filters need one, so they are not offered for
        the rest — a column of invented numbers would make this panel look
        finished and make it dangerous.
      </p>

      <div className="jg-ws-table-wrap">
        <table className="jg-ws-table jg-screener-table">
          <thead>
            <tr>
              <th>Symbol</th><th>Name</th><th>Class</th>
              <th>Status</th><th>Change</th><th>RSI</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr key={row.symbol}
                  className={row.symbol === currentSymbol ? "current" : ""}>
                <td>{row.symbol}</td>
                <td className="jg-screener-name">{row.display_name}</td>
                <td>{CLASS_LABEL[row.asset_class] ?? row.asset_class}</td>
                <td>
                  <span className={`jg-symbol-status ${row.status.toLowerCase()}`}>
                    {STATUS_LABEL[row.status] ?? row.status}
                  </span>
                </td>
                {/* No feed, no number. The dash is the honest value. */}
                <td className="jg-screener-empty">
                  {row.priceable ? "on chart" : "—"}
                </td>
                <td className="jg-screener-empty">
                  {row.priceable ? "on chart" : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length === 0 && (
        <p className="jg-cc-note">Nothing matches those filters.</p>
      )}

      <p className="jg-screener-note">
        Trend, ADX, volatility, opportunity score and setup class filters —
        DATA UNAVAILABLE. Each needs a price history per instrument, which
        arrives with the feeds.
      </p>
    </div>
  );
}
