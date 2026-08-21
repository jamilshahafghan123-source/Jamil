import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { money } from "../lib/format";
import type {
  DemoAccountState, DemoPerformance, DemoTrade,
} from "../lib/types";

/**
 * Account and performance (sections 12, 15).
 *
 * Sections rather than cards, and collapsed rather than stacked. This is
 * a 266px panel beside a chart, not a dashboard: a grid of large tiles
 * would push the numbers a trader checks every few minutes below the fold
 * to make room for ones they check twice a day.
 *
 * Every figure is computed from real rows — the demo account for balance
 * and equity, closed trades for everything else. A day with no trades
 * shows zeros; a figure the platform does not have shows an em dash. No
 * sample performance appears here at any point, including while loading.
 */

function tone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value === 0) return "";
  return value > 0 ? "up" : "down";
}

/** Lifetime totals, counted from the trades themselves. */
function lifetime(trades: DemoTrade[]) {
  const wins = trades.filter((t) => t.realized_pnl > 0);
  const losses = trades.filter((t) => t.realized_pnl < 0);
  const net = trades.reduce((sum, t) => sum + t.realized_pnl, 0);
  const best = trades.reduce<number | null>(
    (top, t) => (top == null || t.realized_pnl > top ? t.realized_pnl : top),
    null,
  );
  const worst = trades.reduce<number | null>(
    (low, t) => (low == null || t.realized_pnl < low ? t.realized_pnl : low),
    null,
  );
  return {
    count: trades.length,
    wins: wins.length,
    losses: losses.length,
    breakeven: trades.length - wins.length - losses.length,
    net,
    best,
    worst,
    // Null until there is something to take a rate of. A win rate off no
    // trades is not 0%; it is unknown, and 0% reads as a losing record.
    winRate: trades.length ? (wins.length / trades.length) * 100 : null,
  };
}

export function AccountPanel({
  account, currency, trades, onReset, resetLabel, labels,
}: {
  account: DemoAccountState | null;
  currency: string;
  /** Closed trades, already loaded by the workspace. */
  trades: DemoTrade[];
  onReset: () => void;
  resetLabel: string;
  labels: {
    balance: string; equity: string; freeMargin: string;
    floatingPnl: string; realisedPnl: string;
  };
}) {
  const [performance, setPerformance] = useState<DemoPerformance | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api.demoPerformance()
      .then((p) => { if (!cancelled) { setPerformance(p); setError(null); } })
      .catch((err) => {
        if (cancelled) return;
        // Reported, not replaced with zeros: an outage and a quiet day
        // must not look the same.
        setPerformance(null);
        setError(err instanceof Error ? err.message : "Unavailable");
      });
    return () => { cancelled = true; };
  }, [trades.length]);

  const today = performance?.today ?? null;
  const all = lifetime(trades);

  return (
    <div className="jg-account-panel">
      <p className="jg-ws-virtual">VIRTUAL MONEY — J Gold AI demo</p>

      <details className="jg-acc-section" open>
        <summary>Account</summary>
        <dl className="jg-account-list">
          <div><dt>{labels.balance}</dt>
               <dd>{money(account?.balance, currency)}</dd></div>
          <div><dt>{labels.equity}</dt>
               <dd>{money(account?.equity, currency)}</dd></div>
          <div><dt>{labels.freeMargin}</dt>
               <dd>{money(account?.free_margin, currency)}</dd></div>
          <div><dt>{labels.floatingPnl}</dt>
               <dd className={tone(account?.floating_pnl)}>
                 {money(account?.floating_pnl, currency)}</dd></div>
          <div><dt>{labels.realisedPnl}</dt>
               <dd className={tone(account?.realized_pnl)}>
                 {money(account?.realized_pnl, currency)}</dd></div>
          <div><dt>Open positions</dt>
               <dd>{account?.open_positions ?? 0}</dd></div>
        </dl>
      </details>

      <details className="jg-acc-section" open>
        <summary>
          Today
          {performance && (
            <span className="jg-acc-basis">
              {" "}{performance.day_basis}
            </span>
          )}
        </summary>
        {error ? (
          <p className="jg-cc-note">
            DATA UNAVAILABLE — {error}. Zeros are not shown in its place,
            because an outage and a quiet day are not the same thing.
          </p>
        ) : (
          <dl className="jg-account-list">
            <div><dt>Net P/L</dt>
                 <dd className={tone(today?.net_pnl)}>
                   {money(today?.net_pnl, currency)}</dd></div>
            <div><dt>Trades</dt><dd>{today?.trades ?? "—"}</dd></div>
            <div><dt>Wins</dt><dd>{today?.wins ?? "—"}</dd></div>
            <div><dt>Losses</dt><dd>{today?.losses ?? "—"}</dd></div>
            <div><dt>Win rate</dt>
                 <dd>{today?.win_rate != null ? `${today.win_rate}%` : "—"}</dd></div>
          </dl>
        )}
      </details>

      <details className="jg-acc-section">
        <summary>All time</summary>
        {all.count === 0 ? (
          <p className="jg-cc-note">
            No trades have closed on this account yet.
          </p>
        ) : (
          <dl className="jg-account-list">
            <div><dt>Trades</dt><dd>{all.count}</dd></div>
            <div><dt>Wins</dt><dd>{all.wins}</dd></div>
            <div><dt>Losses</dt><dd>{all.losses}</dd></div>
            {all.breakeven > 0 && (
              <div><dt>Break-even</dt><dd>{all.breakeven}</dd></div>
            )}
            <div><dt>Win rate</dt>
                 <dd>{all.winRate != null
                   ? `${all.winRate.toFixed(1)}%` : "—"}</dd></div>
            <div><dt>Net realised</dt>
                 <dd className={tone(all.net)}>{money(all.net, currency)}</dd></div>
            <div><dt>Best</dt>
                 <dd className={tone(all.best)}>{money(all.best, currency)}</dd></div>
            <div><dt>Worst</dt>
                 <dd className={tone(all.worst)}>{money(all.worst, currency)}</dd></div>
          </dl>
        )}
        <p className="jg-data-note">
          Counted from the {trades.length} most recent closed trades this
          browser has loaded, not from a stored lifetime total.
        </p>
      </details>

      <button type="button" className="btn sm" onClick={onReset}>
        {resetLabel}
      </button>
    </div>
  );
}
