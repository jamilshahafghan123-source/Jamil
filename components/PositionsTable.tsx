"use client";

import { useState } from "react";

import { ApiClientError, apiFetch } from "@/lib/client";
import { clock, number, price, signed, timeAgo } from "@/lib/format";
import type { OrderOutcome, Position } from "@/lib/types";
import type { PollState } from "@/hooks/usePolling";
import { ErrorNotice, Panel, RefreshIndicator, SkeletonRows, humanizeCode } from "./ui";

/** Real open MT5 positions, with a close action per row. */
export default function PositionsTable({
  state,
  liveExecutionEnabled,
  online,
  onClosed,
}: {
  state: PollState<Position[]>;
  liveExecutionEnabled: boolean;
  online: boolean;
  onClosed: () => void;
}) {
  const { data: positions, error, loading, refreshing, lastUpdated, refresh } = state;
  const [closing, setClosing] = useState<number | null>(null);
  const [outcome, setOutcome] = useState<
    { ticket: number; ok: boolean; title: string; message: string; result?: OrderOutcome } | null
  >(null);

  async function close(ticket: number) {
    setClosing(ticket);
    setOutcome(null);
    try {
      const result = await apiFetch<OrderOutcome>(`/api/mt5/positions/${ticket}/close`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      setOutcome({
        ticket,
        ok: true,
        title: `Position ${ticket} closed`,
        message: `MT5 retcode ${result.retcode} — ${result.retcode_description}`,
        result,
      });
      onClosed();
    } catch (caught) {
      const err = caught as ApiClientError;
      setOutcome({
        ticket,
        ok: false,
        title: err.offline ? "MT5 Bridge Offline" : humanizeCode(err.code),
        message: err.message,
      });
    } finally {
      setClosing(null);
    }
  }

  return (
    <Panel
      title="Open positions"
      tight
      actions={
        <RefreshIndicator
          refreshing={refreshing}
          label={
            online
              ? `${positions?.length ?? 0} open · updated ${timeAgo(lastUpdated)}`
              : "unavailable"
          }
        />
      }
    >
      {outcome ? (
        <div style={{ padding: 12, borderBottom: "1px solid var(--border)" }}>
          <div className={outcome.ok ? "notice ok" : "notice error"} role="status">
            <div>
              <strong>{outcome.title}</strong>
              <span>{outcome.message}</span>
              {outcome.result ? (
                <div className="result-detail">
                  {outcome.result.deal ? <span>deal #{outcome.result.deal}</span> : null}
                  {outcome.result.volume ? <span>volume {outcome.result.volume}</span> : null}
                  {outcome.result.price ? <span>price {outcome.result.price}</span> : null}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {!online && !positions ? (
        <div className="empty">
          Positions are unavailable while the MT5 bridge is offline.
        </div>
      ) : null}

      {online && loading && !positions ? (
        <div style={{ padding: 14 }}>
          <SkeletonRows rows={3} />
        </div>
      ) : null}

      {error && !positions ? (
        <div style={{ padding: 14 }}>
          <ErrorNotice error={error} onRetry={refresh} />
        </div>
      ) : null}

      {positions && positions.length === 0 ? (
        <div className="empty">No open positions on this MT5 account.</div>
      ) : null}

      {positions && positions.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ticket</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Volume</th>
                <th>Open</th>
                <th>Current</th>
                <th>S/L</th>
                <th>T/P</th>
                <th>Profit</th>
                <th>Opened</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => (
                <tr key={position.ticket}>
                  <td className="muted">{position.ticket}</td>
                  <td>{position.symbol}</td>
                  <td>
                    <span className={position.side === "buy" ? "pill buy" : "pill sell"}>
                      {position.side.toUpperCase()}
                    </span>
                  </td>
                  <td>{number(position.volume, 2)}</td>
                  <td>{price(position.price_open)}</td>
                  <td>{price(position.price_current)}</td>
                  <td className="muted">{price(position.sl)}</td>
                  <td className="muted">{price(position.tp)}</td>
                  <td className={position.profit >= 0 ? "up" : "down"}>
                    {signed(position.profit)}
                  </td>
                  <td className="muted">{clock(position.time)}</td>
                  <td>
                    <button
                      type="button"
                      className="btn small"
                      disabled={closing === position.ticket || !liveExecutionEnabled}
                      onClick={() => close(position.ticket)}
                      title={
                        liveExecutionEnabled
                          ? `Close position ${position.ticket} on MT5`
                          : "Live execution is disabled on the server (MT5_ALLOW_LIVE_ORDERS)"
                      }
                    >
                      {closing === position.ticket ? "Closing…" : "Close"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Panel>
  );
}
