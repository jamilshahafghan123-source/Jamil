"use client";

import { number, price, timeAgo } from "@/lib/format";
import type { SignalResult } from "@/lib/types";
import type { PollState } from "@/hooks/usePolling";
import { ErrorNotice, Panel, RefreshIndicator, SkeletonRows } from "./ui";

const STAGE_LABELS: Record<string, string> = {
  trend: "Trend",
  support_resistance: "Support / resistance",
  momentum: "Momentum",
  volatility: "Volatility",
};

/**
 * The analysis pipeline's read, stage by stage. Proposals are never sent from
 * here — "Load into ticket" fills the order form and a human presses the button.
 */
export default function SignalPanel({
  state,
  online,
  digits,
  onUseProposal,
}: {
  state: PollState<SignalResult>;
  online: boolean;
  digits: number;
  onUseProposal: (proposal: NonNullable<SignalResult["proposal"]>) => void;
}) {
  const { data: signal, error, loading, refreshing, lastUpdated, refresh } = state;

  if (!online && !signal) {
    return (
      <Panel title="Signal">
        <div className="empty">Analysis is unavailable while the MT5 bridge is offline.</div>
      </Panel>
    );
  }

  if (loading && !signal) {
    return (
      <Panel title="Signal">
        <SkeletonRows rows={4} />
      </Panel>
    );
  }

  if (error && !signal) {
    return (
      <Panel title="Signal">
        <ErrorNotice error={error} onRetry={refresh} />
      </Panel>
    );
  }

  if (!signal) return null;

  const trade = signal.decision === "trade";
  const vetoed = signal.risk?.passed === false;

  return (
    <Panel
      title="Signal"
      actions={
        <RefreshIndicator
          refreshing={refreshing}
          label={`${signal.timeframe} · ${signal.candles} bars · ${timeAgo(lastUpdated)}`}
        />
      }
    >
      <div className="verdict">
        <span className={trade ? `verdict-badge ${signal.setup?.side}` : "verdict-badge flat"}>
          {trade ? `TRADE · ${signal.setup?.side.toUpperCase()}` : "NO TRADE"}
        </span>
        <div className="verdict-confidence">
          <div className="risk-meter-head">
            <span className="muted">Confidence</span>
            <span className="mono">
              {number(signal.confidence, 0)} / {number(signal.min_confidence, 0)} needed
            </span>
          </div>
          <div className="risk-bar">
            <span
              style={{
                width: `${Math.min(100, signal.confidence)}%`,
                background: trade ? "var(--up)" : "var(--muted)",
              }}
            />
          </div>
        </div>
      </div>

      <ol className="pipeline">
        {Object.entries(signal.stages).map(([key, stage]) => (
          <li key={key}>
            <div className="pipeline-head">
              <span className="pipeline-name">{STAGE_LABELS[key] ?? stage.name}</span>
              <span
                className={
                  stage.direction === "buy"
                    ? "pill buy"
                    : stage.direction === "sell"
                      ? "pill sell"
                      : "pill"
                }
              >
                {stage.direction === "flat" ? "NEUTRAL" : stage.direction.toUpperCase()}
              </span>
            </div>
            <p className="pipeline-note">{stage.note}</p>
          </li>
        ))}
      </ol>

      {signal.setup ? (
        <dl className="risk-grid" style={{ marginTop: 12 }}>
          <dt>Entry</dt>
          <dd>{price(signal.setup.entry, digits)}</dd>
          <dt>Stop loss</dt>
          <dd className="down">{price(signal.setup.stop_loss, digits)}</dd>
          <dt>Take profit</dt>
          <dd className="up">{price(signal.setup.take_profit, digits)}</dd>
          <dt>Reward : risk</dt>
          <dd>
            {number(signal.setup.reward_ratio, 2)}
            {signal.setup.target_capped_by_level ? " (capped at level)" : ""}
          </dd>
          {signal.proposal ? (
            <>
              <dt>Sized volume</dt>
              <dd>{number(signal.proposal.volume, 2)}</dd>
            </>
          ) : null}
        </dl>
      ) : null}

      {!trade ? (
        <div className={vetoed ? "notice error" : "notice"} style={{ marginTop: 12 }}>
          <div>
            <strong>{vetoed ? "Risk manager vetoed this setup" : "No trade"}</strong>
            <span>{signal.reasons[0]}</span>
          </div>
        </div>
      ) : null}

      {trade && signal.proposal ? (
        <button
          type="button"
          className={`btn ${signal.proposal.side}`}
          style={{ width: "100%", marginTop: 12 }}
          onClick={() => onUseProposal(signal.proposal!)}
        >
          Load into ticket · {signal.proposal.side} {number(signal.proposal.volume, 2)}
        </button>
      ) : null}

      <p className="hint" style={{ marginTop: 10, color: "var(--muted)" }}>
        Analysis only. Nothing is placed until you send the ticket, and the risk policy is
        applied again at that point.
      </p>
    </Panel>
  );
}
