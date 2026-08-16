"use client";

import { number, price, timeAgo } from "@/lib/format";
import type { SignalResult, TimeframeRead } from "@/lib/types";
import type { PollState } from "@/hooks/usePolling";
import { ErrorNotice, Panel, RefreshIndicator, SkeletonRows } from "./ui";

/** What each timeframe is responsible for, in the order the engine consults them. */
const ROLES: { key: string; label: string; job: string }[] = [
  { key: "trend", label: "Trend", job: "main direction" },
  { key: "structure", label: "Structure", job: "swings + momentum" },
  { key: "trigger", label: "Trigger", job: "entry timing" },
];

const BIAS_PILL: Record<string, string> = {
  bullish: "pill buy",
  bearish: "pill sell",
  neutral: "pill",
};

/**
 * The XAUUSD strategy's verdict: BUY, SELL or NO_TRADE, with the three
 * timeframes that produced it and the levels it would trade.
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

  const trading = signal.direction !== "NO_TRADE";
  const vetoed = signal.risk?.passed === false;
  const roles = signal.timeframe_confirmation.roles;
  const scorePct = Math.min(100, signal.signal_score);

  return (
    <Panel
      title="Signal"
      actions={
        <RefreshIndicator
          refreshing={refreshing}
          label={`${signal.trend.trend_timeframe}/${signal.trend.structure_timeframe}/${signal.trend.trigger_timeframe} · ${timeAgo(lastUpdated)}`}
        />
      }
    >
      <div className="verdict">
        <span
          className={
            trading
              ? `verdict-badge ${signal.direction === "BUY" ? "buy" : "sell"}`
              : "verdict-badge flat"
          }
        >
          {signal.direction.replace("_", " ")}
        </span>
        <div className="verdict-confidence">
          <div className="risk-meter-head">
            <span className="muted">Signal score</span>
            <span className="mono">
              {number(signal.signal_score, 0)} / {number(signal.min_score, 0)} needed
            </span>
          </div>
          <div className="risk-bar">
            <span
              style={{
                width: `${scorePct}%`,
                background: trading ? "var(--up)" : "var(--muted)",
              }}
            />
          </div>
        </div>
      </div>

      <ol className="pipeline">
        {ROLES.map(({ key, label, job }) => {
          const read = roles[key] as TimeframeRead | undefined;
          return (
            <li key={key}>
              <div className="pipeline-head">
                <span className="pipeline-name">
                  {label}
                  <span className="muted" style={{ fontWeight: 400 }}>
                    {" "}
                    · {read?.timeframe ?? "—"} · {job}
                  </span>
                </span>
                <span className={BIAS_PILL[read?.bias ?? "neutral"]}>
                  {(read?.bias ?? "not reached").toUpperCase()}
                </span>
              </div>
              <p className="pipeline-note">
                {read?.reasons?.[0] ?? "Not evaluated — an earlier timeframe stopped the signal."}
              </p>
            </li>
          );
        })}
      </ol>

      {trading && signal.entry != null && signal.stop_loss != null ? (
        <dl className="risk-grid" style={{ marginTop: 12 }}>
          <dt>Entry</dt>
          <dd>{price(signal.entry, digits)}</dd>
          <dt>Stop loss</dt>
          <dd className="down">{price(signal.stop_loss, digits)}</dd>
          {(["tp1", "tp2", "tp3"] as const).map((key) => (
            <TargetRow
              key={key}
              label={key.toUpperCase()}
              value={signal.take_profit[key]}
              ratio={signal.risk_reward[key]}
              digits={digits}
              isOrderTarget={signal.order_target === key}
            />
          ))}
          {signal.proposal ? (
            <>
              <dt>Sized volume</dt>
              <dd>{number(signal.proposal.volume, 2)}</dd>
            </>
          ) : null}
        </dl>
      ) : null}

      {!trading || vetoed ? (
        <div className={vetoed ? "notice error" : "notice"} style={{ marginTop: 12 }}>
          <div>
            <strong>{vetoed ? "Risk manager vetoed this setup" : "No trade"}</strong>
            <span>{signal.reasons[0]}</span>
          </div>
        </div>
      ) : null}

      {trading && !vetoed && signal.proposal ? (
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
        Read from closed candles only. Analysis proposes; nothing is placed until you send the
        ticket, and the risk policy is applied again at that point.
      </p>
    </Panel>
  );
}

function TargetRow({
  label,
  value,
  ratio,
  digits,
  isOrderTarget,
}: {
  label: string;
  value: number | null;
  ratio: number | null;
  digits: number;
  isOrderTarget: boolean;
}) {
  return (
    <>
      <dt>
        {label}
        {ratio ? <span className="muted"> · {number(ratio, 1)}R</span> : null}
        {isOrderTarget ? <span className="muted"> · on order</span> : null}
      </dt>
      <dd className="up">{price(value, digits)}</dd>
    </>
  );
}
